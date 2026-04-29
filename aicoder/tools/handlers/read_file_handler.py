"""read_file Handler — 带行号、缓存和去重"""
import os, time
from pathlib import Path
from .base import ToolHandler
from ..result import ToolCall, ToolResult

DEFAULT_MAX_LINES = 500
FILE_TRUNCATED_MARKER = "\n\n---\n\n[FILE TRUNCATED:"


class ReadFileHandler(ToolHandler):
    name = "read_file"
    requires_approval = False

    def __init__(self):
        self._cache: dict[str, dict] = {}

    def validate_params(self, tool_call: ToolCall) -> str:
        if not tool_call.get("path"):
            return "Missing required parameter: path"
        return ""

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        rel_path = tool_call.get("path")
        full_path = coder.abs_root_path(rel_path)

        if not os.path.isfile(full_path):
            return ToolResult.fail(self.name, f"File not found: {rel_path}")

        # 去重缓存检查
        cache_key = full_path.lower()
        cached = self._cache.get(cache_key)
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            mtime = 0

        if cached:
            if cached["mtime"] == mtime:
                cached["read_count"] += 1
                if cached["read_count"] >= 3:
                    return ToolResult.fail(
                        self.name,
                        f"[DUPLICATE READ] You have already read '{rel_path}' "
                        f"{cached['read_count']} times. Use the information you already have."
                    )
                prefix = f"[File already read] '{rel_path}' was read earlier (read #{cached['read_count']}).\n\n"
            else:
                # 文件被修改过，清除缓存重新读取
                del self._cache[cache_key]
                prefix = ""
        else:
            prefix = ""

        # 读取文件
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            return ToolResult.fail(self.name, f"Error reading file: {e}")

        # 截断检测
        truncated = False
        if FILE_TRUNCATED_MARKER in content:
            idx = content.index(FILE_TRUNCATED_MARKER)
            content = content[:idx]
            truncated = True

        lines = content.splitlines()
        total_lines = len(lines)

        # 行范围解析
        start = self._parse_int(tool_call.get("start_line"), 1)
        end = self._parse_int(tool_call.get("end_line"), None)
        if end is None:
            end = min(start + DEFAULT_MAX_LINES - 1, total_lines)

        # 边界修正
        start = max(1, min(start, total_lines))
        end = max(start, min(end, total_lines))

        # 格式化输出（带行号）
        selected = lines[start - 1:end]
        output_lines = []
        for i, line in enumerate(selected, start=start):
            output_lines.append(f"{i:>5} | {line}")

        result = prefix + "\n".join(output_lines)

        # 后缀提示
        if truncated:
            result += f"\n\n[FILE TRUNCATED — content exceeds display limit]"
        if end < total_lines:
            result += f"\n\n(Showing lines {start}-{end} of {total_lines}. "
            result += f"Use read_file with start_line={end + 1} to continue.)"
        else:
            result += f"\n\n(File has {total_lines} lines total.)"

        # 更新缓存
        if not cached or cached.get("mtime") != mtime:
            self._cache[cache_key] = {"read_count": 1, "mtime": mtime}

        return ToolResult.ok(self.name, result)

    def _parse_int(self, value: str, default: int | None) -> int:
        if not value or not value.strip():
            return default if default is not None else 1
        try:
            return int(value.strip())
        except ValueError:
            return default if default is not None else 1
