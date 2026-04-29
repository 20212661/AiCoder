"""search_files Handler — ripgrep 搜索，参考 Cline 的 --json + context + 按文件分组"""
import subprocess, os, json
from .base import ToolHandler
from ..result import ToolCall, ToolResult

MAX_RESULTS = 300
MAX_OUTPUT_BYTES = 200 * 1024  # 200KB

class SearchFilesHandler(ToolHandler):
    name = "search_files"
    requires_approval = False

    def validate_params(self, tool_call: ToolCall) -> str:
        if not tool_call.get("path"):
            return "Missing required parameter: path"
        if not tool_call.get("regex"):
            return "Missing required parameter: regex"
        return ""

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        rel_path = tool_call.get("path")
        regex = tool_call.get("regex")
        file_pattern = tool_call.get("file_pattern", "")

        full_path = coder.abs_root_path(rel_path)
        if not os.path.isdir(full_path):
            full_path = os.path.dirname(full_path)
            if not os.path.isdir(full_path):
                return ToolResult.fail(self.name, f"Directory not found: {rel_path}")

        # 优先 ripgrep --json，回退 grep
        try:
            output = self._search_rg(full_path, regex, file_pattern, coder.root)
            if output is not None:
                return ToolResult.ok(self.name, output)
        except Exception:
            pass

        try:
            output = self._search_grep(full_path, regex, file_pattern)
            if output is not None:
                return ToolResult.ok(self.name, output)
        except Exception:
            pass

        return ToolResult.fail(self.name, "Neither ripgrep nor grep is available")

    def _search_rg(self, full_path: str, regex: str, file_pattern: str, cwd: str) -> str | None:
        """使用 ripgrep --json 搜索，按文件分组输出"""
        args = ["rg", "--json", "-e", regex, "--context", "1",
                "--max-count", str(MAX_RESULTS), full_path]
        if file_pattern:
            args.insert(-2, "--glob")
            args.insert(-2, file_pattern)

        result = subprocess.run(args, capture_output=True, text=True,
                                cwd=cwd, timeout=30)

        if result.returncode > 1:
            return None  # rg failed

        # 解析 JSON 行输出
        lines = result.stdout.strip().splitlines()
        if not lines:
            return f"No matches found for '{regex}' in {os.path.relpath(full_path, cwd)}"

        results_by_file: dict[str, list[dict]] = {}
        current_result: dict | None = None
        match_count = 0

        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") == "match":
                data = obj["data"]
                file_path = os.path.relpath(data["path"]["text"], cwd)
                line_num = data["line_number"]
                match_text = data["lines"]["text"].rstrip()

                if file_path not in results_by_file:
                    results_by_file[file_path] = []
                results_by_file[file_path].append({
                    "line": line_num, "text": match_text
                })
                match_count += 1
                current_result = None

            elif obj.get("type") == "context" and current_result is None:
                # 上下文行（已融入 match 的 lines.text，跳过）
                pass

        if not results_by_file:
            return f"No matches found for '{regex}'"

        # 格式化：按文件分组
        cwd_path = cwd.rstrip("/") + "/"
        output_parts = []
        total_bytes = 0
        shown = 0
        truncated = False

        for file_path, matches in results_by_file.items():
            # 字节限制
            file_header = file_path.replace(cwd_path, "") + "\n|----\n"
            if total_bytes + len(file_header) >= MAX_OUTPUT_BYTES:
                truncated = True
                break

            output_parts.append(file_header)
            total_bytes += len(file_header)

            for m in matches:
                shown += 1
                line_text = f"|{m['line']:>5}: {m['text']}\n"
                if total_bytes + len(line_text) >= MAX_OUTPUT_BYTES:
                    truncated = True
                    break
                output_parts.append(line_text)
                total_bytes += len(line_text)

            output_parts.append("|----\n\n")
            total_bytes += 8

            if truncated or shown >= MAX_RESULTS:
                break

        result = "".join(output_parts)
        result += f"\nFound {match_count} matches for '{regex}'"

        if truncated:
            result += f"\n[Results truncated at {MAX_OUTPUT_BYTES // 1024}KB limit]"
        if shown >= MAX_RESULTS:
            result += f"\n[Showing first {MAX_RESULTS} results]"

        return result

    def _search_grep(self, full_path: str, regex: str, file_pattern: str) -> str | None:
        """回退方案：grep -rn"""
        args = ["grep", "-rn", "--max-count=" + str(MAX_RESULTS), regex, full_path]
        if file_pattern:
            args.insert(2, "--include=" + file_pattern)

        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if result.returncode > 1:
            return None

        output = result.stdout.strip()
        if not output:
            return f"No matches found for '{regex}'"

        lines = output.splitlines()
        count = len(lines)
        if count > MAX_RESULTS:
            lines = lines[:MAX_RESULTS]

        # 按文件分组
        results_by_file: dict[str, list[str]] = {}
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                f = parts[0]
                results_by_file.setdefault(f, []).append(f"{parts[1]:>5}: {parts[2]}")

        output_parts = []
        for f, matches in results_by_file.items():
            output_parts.append(f + "\n|----\n")
            for m in matches[:50]:
                output_parts.append("|" + m + "\n")
            output_parts.append("|----\n\n")

        result = "".join(output_parts)
        result += f"\nFound {count} matches for '{regex}'"
        if count > MAX_RESULTS:
            result += f"\n[Showing first {MAX_RESULTS} results]"
        return result
