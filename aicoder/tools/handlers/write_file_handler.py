"""write_file Handler — 整文件写入，带内容清理和路径安全"""
import os
from pathlib import Path
from .base import ToolHandler
from ..result import ToolCall, ToolResult, build_unified_diff

MAX_WRITE_BYTES = 2 * 1024 * 1024  # 2MB per file write
BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o", ".a",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".sqlite", ".db", ".woff", ".woff2", ".ttf", ".eot",
})


class WriteFileHandler(ToolHandler):
    name = "write_file"
    requires_approval = True

    def validate_params(self, tool_call: ToolCall) -> str:
        if not tool_call.get("path"):
            return "Missing required parameter: path"
        if not tool_call.get("content"):
            return "Missing required parameter: content"
        return ""

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        path = tool_call.get("path")
        content = tool_call.get("content")

        # 内容清理：去除 LLM 可能多加的 markdown 围栏
        content = self._clean_content(content)

        # 文件大小检查
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > MAX_WRITE_BYTES:
            return ToolResult.fail(
                self.name,
                f"Content too large: {content_bytes} bytes exceeds {MAX_WRITE_BYTES} byte limit. "
                "Use edit_file for targeted changes."
            )

        full_path = coder.abs_root_path(path)

        # 二次校验：确保解析后的绝对路径仍在工作区内
        resolved = str(Path(full_path).resolve())
        root_resolved = str(Path(coder.root).resolve())
        if not resolved.startswith(root_resolved + os.sep) and resolved != root_resolved:
            return ToolResult.fail(
                self.name,
                f"Path traversal blocked: {path} resolves outside workspace {coder.root}"
            )

        # 二进制文件保护
        ext = Path(resolved).suffix.lower()
        if ext in BINARY_EXTENSIONS:
            return ToolResult.fail(
                self.name,
                f"Cannot write binary file type: {ext}. "
                "Binary files should not be written via text tools."
            )

        # 确保目录存在
        Path(full_path).parent.mkdir(parents=True, exist_ok=True)

        # 检查是否已存在（用于结果消息区分创建/更新）
        existed = Path(full_path).exists()
        existing = coder.io.read_text(full_path) or ""

        # 写入
        coder.io.write_text(full_path, content)
        abs_path = str(Path(full_path).resolve())
        if abs_path not in coder.abs_fnames:
            coder.abs_fnames.add(abs_path)

        action = "Updated" if existed else "Created"
        diff = build_unified_diff(existing, content, path)
        return ToolResult.ok(
            self.name,
            f"{action} {path} ({len(content)} bytes)\n\n"
            f"The file content was successfully saved.",
            meta={
                "path": path,
                "action": action,
                "diff": diff,
                "content": content,
            },
        )

    @staticmethod
    def _clean_content(content: str) -> str:
        """清理 LLM 输出中可能包含的 markdown 围栏"""
        lines = content.splitlines(keepends=True)
        if not lines:
            return content

        # 去除开头的 ``` 行（可能有语言标记）
        first = lines[0].strip()
        if first.startswith("```"):
            lines = lines[1:]

        # 去除结尾的 ``` 行
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        return "".join(lines)
