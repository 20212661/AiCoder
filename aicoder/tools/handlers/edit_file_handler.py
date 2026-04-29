"""edit_file Handler — SEARCH/REPLACE 文件编辑，带改进的错误报告"""
from pathlib import Path
from .base import ToolHandler
from ..result import ToolCall, ToolResult, build_unified_diff
from ...coders.editblock_coder import do_replace, find_similar_lines, strip_quoted_wrapping


class EditFileHandler(ToolHandler):
    name = "edit_file"
    requires_approval = False

    def validate_params(self, tool_call: ToolCall) -> str:
        if not tool_call.get("path"):
            return "Missing required parameter: path"
        if not tool_call.get("search") and not tool_call.get("replace"):
            return "Missing: both search and replace are empty"
        return ""

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        path = tool_call.get("path")
        search = tool_call.get("search")
        replace = tool_call.get("replace")

        full_path = coder.abs_root_path(path)
        existed = Path(full_path).exists()

        # 读取现有内容
        existing = coder.io.read_text(full_path) or ""

        # 调用现有的 do_replace 算法（含 5 级模糊匹配）
        search_clean = strip_quoted_wrapping(search, path, coder.fence)
        replace_clean = strip_quoted_wrapping(replace, path, coder.fence)
        new_content = do_replace(full_path, existing, search_clean, replace_clean, coder.fence)

        # 如果主文件没匹配上，尝试在其他聊天文件中查找
        if new_content is None and search.strip():
            for fp in coder.abs_fnames:
                content = coder.io.read_text(fp) or ""
                new_content = do_replace(fp, content, search_clean, replace_clean, coder.fence)
                if new_content:
                    full_path = fp
                    path = coder.get_rel_fname(fp)
                    break

        if new_content is None:
            # 构建详细的错误信息
            msg_parts = [f"SEARCH block not found in {path}."]

            if not existed:
                msg_parts.append(f"File does not exist. Use write_file to create it.")
            elif not search.strip():
                msg_parts.append("SEARCH is empty. To create a new file, use write_file instead.")
            else:
                # 提供 "did you mean?" 建议
                suggestion = find_similar_lines(search, existing) if existing else ""
                if suggestion:
                    msg_parts.append(f"\nDid you mean to match these lines?\n```\n{suggestion}\n```")

                # 检查 replace 是否已经存在
                if replace.strip() and replace.strip() in existing:
                    msg_parts.append("\nNOTE: The REPLACE content already exists in this file. "
                                     "The edit may not be needed.")

                msg_parts.append("\nThe SEARCH text must match exactly, including all whitespace, "
                                 "comments, and indentation.")

            return ToolResult.fail(self.name, "\n".join(msg_parts))

        # 写入文件
        coder.io.write_text(full_path, new_content)
        abs_path = str(Path(full_path).resolve())
        if abs_path not in coder.abs_fnames:
            coder.abs_fnames.add(abs_path)

        action = "Updated" if existed else "Created"
        diff = build_unified_diff(existing, new_content, path)
        return ToolResult.ok(
            self.name,
            f"{action} {path}",
            meta={
                "path": path,
                "action": action,
                "diff": diff,
                "content": new_content,
            },
        )
