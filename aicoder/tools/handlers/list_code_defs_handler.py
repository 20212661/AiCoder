"""list_code_defs Handler — 列出代码定义，复用 repomap 的 tree-sitter 解析"""
import os
from pathlib import Path
from .base import ToolHandler
from ..result import ToolCall, ToolResult

MAX_FILES = 50
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".rs", ".go", ".java", ".c", ".h", ".cpp", ".hpp",
    ".rb", ".swift", ".kt", ".cs", ".php",
}


class ListCodeDefsHandler(ToolHandler):
    name = "list_code_defs"
    requires_approval = False

    def validate_params(self, tool_call: ToolCall) -> str:
        if not tool_call.get("path"):
            return "Missing required parameter: path"
        return ""

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        rel_path = tool_call.get("path")
        full_path = coder.abs_root_path(rel_path)

        # 支持单文件：直接解析该文件
        if os.path.isfile(full_path):
            ext = os.path.splitext(full_path)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                return ToolResult.ok(
                    self.name,
                    f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                )
            result = self._extract_definitions(
                os.path.dirname(full_path), [full_path], os.path.dirname(rel_path) or "."
            )
            if not result.strip():
                return ToolResult.ok(self.name, f"No definitions found in {rel_path}")
            return ToolResult.ok(self.name, result)

        if not os.path.isdir(full_path):
            return ToolResult.fail(self.name, f"Path not found: {rel_path}")

        # 收集顶层源文件（非递归）
        source_files = self._collect_source_files(full_path)

        if not source_files:
            return ToolResult.ok(
                self.name,
                f"No supported source files found in {rel_path}. "
                f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        # 用 repomap 的 tree-sitter 提取定义
        result = self._extract_definitions(full_path, source_files, rel_path)

        if not result.strip():
            return ToolResult.ok(self.name, f"No definitions found in {rel_path}")

        return ToolResult.ok(self.name, result)

    def _collect_source_files(self, dir_path: str) -> list[str]:
        """收集目录中的源文件（顶层，最多 MAX_FILES 个）"""
        files = []
        try:
            entries = sorted(os.listdir(dir_path))
        except PermissionError:
            return []

        for entry in entries:
            abs_path = os.path.join(dir_path, entry)
            if os.path.isfile(abs_path):
                ext = os.path.splitext(entry)[1].lower()
                if ext in SUPPORTED_EXTENSIONS and not entry.startswith("."):
                    files.append(abs_path)
            if len(files) >= MAX_FILES:
                break

        return files

    def _extract_definitions(self, root: str, files: list[str], rel_root: str) -> str:
        """用 tree-sitter 提取每个文件的定义名"""
        output_parts = []

        for abs_path in files:
            rel = os.path.relpath(abs_path, root)
            try:
                tags = self._get_tags(abs_path, rel)
            except Exception:
                continue

            if not tags:
                continue

            # 只取 kind="def" 的顶层定义
            def_tags = [t for t in tags if t.get("kind") == "def"]

            if not def_tags:
                continue

            output_parts.append(rel)
            output_parts.append("|----")
            for tag in def_tags:
                line = tag.get("line", "?")
                name = tag.get("name", "")
                output_parts.append(f"|{line:>5}: {name}")
            output_parts.append("|----")
            output_parts.append("")

        return "\n".join(output_parts) if output_parts else ""

    def _get_tags(self, abs_path: str, rel_path: str) -> list[dict]:
        """从 repomap 获取文件标签，回退到简单正则解析"""
        try:
            from ...repomap import RepoMap
            # 创建一个最小 RepoMap 实例来复用 tree-sitter 能力
            rm = RepoMap(root=os.path.dirname(abs_path))
            tags = rm.get_tags(abs_path, rel_path)
            result = []
            for tag in tags:
                result.append({
                    "kind": tag.kind,
                    "line": tag.line + 1,  # tree-sitter 0-based → 1-based
                    "name": tag.name,
                })
            return result
        except Exception:
            pass

        # 回退：简单正则匹配常见定义模式
        return self._fallback_parse(abs_path)

    def _fallback_parse(self, abs_path: str) -> list[dict]:
        """简单正则回退：匹配 def/class/fn/function 等"""
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return []

        import re
        patterns = [
            (r'^\s*def\s+(\w+)', "function"),           # Python
            (r'^\s*class\s+(\w+)', "class"),            # Python/Java/Kotlin
            (r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)', "function"),  # JS/TS
            (r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(', "function"),  # JS arrow
            (r'^\s*(?:pub\s+)?fn\s+(\w+)', "function"),  # Rust
            (r'^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', "function"),  # Rust async
            (r'^\s*(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:[\w<>[\]]+\s+)(\w+)\s*\(', "method"),  # Java/C#
            (r'^\s*func\s+(\w+)', "function"),          # Go
            (r'^\s*(?:public\s+|private\s+)?class\s+(\w+)', "class"),  # PHP
        ]

        tags = []
        for line_no, line in enumerate(lines):
            for pattern, kind in patterns:
                m = re.match(pattern, line)
                if m:
                    tags.append({
                        "kind": "def",
                        "line": line_no + 1,
                        "name": m.group(1),
                    })
                    break

        return tags
