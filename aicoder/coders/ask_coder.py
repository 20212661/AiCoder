"""
Ask Coder - 只读问答模式，不编辑代码
显式拦截一切文件写入操作，不依赖提示词约束
"""
from .base_coder import Coder
from .ask_prompts import AskPrompts


class AskCoder(Coder):
    """只读问答 Coder：只回答问题，不做任何编辑

    与基类 Coder 不同，AskCoder 在代码层面拦截所有文件编辑操作，
    而非仅依赖提示词要求 LLM 不要编辑代码。如果 LLM 仍然在回复中
    输出了 SEARCH/REPLACE 或代码块，AskCoder 会检测并拒绝执行。
    """

    edit_format = "ask"
    gpt_prompts = AskPrompts()

    def process_response(self):
        """处理 LLM 响应：扫描编辑尝试并拒绝"""
        content = self.multi_response_content
        if not content:
            return

        # 检测 SEARCH/REPLACE 块
        search_replace_patterns = [
            "<<<<<<< SEARCH",
            "=======",
            ">>>>>>> REPLACE",
        ]
        has_edit_blocks = any(marker in content for marker in search_replace_patterns)

        # 检测代码围栏块（WholeFile 模式的特征标记）
        fence_blocks = 0
        for fence_start, fence_end in self.fences:
            if fence_start in content:
                fence_blocks += 1

        if has_edit_blocks:
            self.io.tool_warning(
                "Ask mode is read-only — SEARCH/REPLACE edits were detected in the LLM's "
                "response but will NOT be applied. Re-run with --edit-format diff or "
                "--edit-format whole to apply edits."
            )
            self.reflected_message = (
                "You are in Ask (read-only) mode. Do not propose SEARCH/REPLACE edits. "
                "Just answer the question or provide the analysis."
            )

        elif content.strip().startswith("```") and fence_blocks >= 2:
            self.io.tool_warning(
                "Ask mode is read-only — code blocks were detected in the LLM's response "
                "but will NOT be written to any files. Re-run with an editing format to "
                "apply code changes."
            )

    def apply_edits(self, edits, dry_run=False):
        """拦截编辑：Ask 模式绝不允许文件写入"""
        # 仅在包含实际文件编辑时警告（过滤 shell 命令）
        file_edits = [e for e in edits if e[0] is not None]
        if file_edits:
            fnames = {e[0] for e in file_edits}
            self.io.tool_warning(
                f"Ask mode is read-only — blocked edit to: {', '.join(sorted(fnames))}"
            )
        return [], []
