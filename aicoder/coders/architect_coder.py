"""
Architect Coder - 双模型协作模式
架构师模型规划变更，编辑模型执行编辑
参考 Aider 的 architect_coder.py
"""
from .architect_prompts import ArchitectPrompts
from .ask_coder import AskCoder
from .base_coder import Coder


class ArchitectCoder(AskCoder):
    """架构师模式：架构师规划，编辑器执行"""

    edit_format = "architect"
    gpt_prompts = ArchitectPrompts()

    def reply_completed(self):
        """架构师回复完成后，创建编辑 Coder 执行变更"""
        content = self.partial_response_content

        if not content or not content.strip():
            return

        # 剥离 architect 回复中可能含有的 XML 工具标签（仅保留纯文本计划）
        from ..tools.parser import parse_xml_tools
        from ..tools.result import TextBlock
        blocks = parse_xml_tools(content, self.tool_registry)
        text_parts = [b.content.strip() for b in blocks if isinstance(b, TextBlock) and b.content.strip()]
        if text_parts:
            content = "\n".join(text_parts)

        if not content.strip():
            return

        if not self.io.confirm_ask("Edit the files based on the architect's plan?"):
            return

        # 创建编辑 Coder
        editor_model = self.main_model
        edit_format = "diff"  # 默认用 diff 格式执行编辑

        kwargs = dict(
            main_model=editor_model,
            edit_format=edit_format,
            auto_commits=self.auto_commits,
            total_cost=self.total_cost,
        )

        new_kwargs = dict(io=self.io, from_coder=self)
        new_kwargs.update(kwargs)

        editor_coder = Coder.create(**new_kwargs)
        editor_coder.cur_messages = []
        editor_coder.done_messages = []
        # Propagate root and repo so the editor operates on the same workspace
        editor_coder.root = self.root
        editor_coder.repo = self.repo

        if self.verbose:
            editor_coder.show_announcements()

        # 用架构师的回复作为编辑器的指令
        editor_coder.run(with_message=content)

        # 传播成本和提交哈希
        self.total_cost = editor_coder.total_cost
        self.aider_commit_hashes.update(editor_coder.aider_commit_hashes)
