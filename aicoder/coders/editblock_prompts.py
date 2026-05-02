"""
EditBlock 提示词模板 - SEARCH/REPLACE diff 格式
参考 Aider 的 editblock_prompts.py
"""
from .base_prompts import CoderPrompts


class EditBlockPrompts(CoderPrompts):
    main_system = """Act as an expert software developer.
For casual conversation or questions, just respond naturally in text.
When the user asks you to modify code, use the XML tools (edit_file, write_file) described in the TOOL USE section.
"""

    system_reminder = """Use the tools listed in the TOOL USE section to read, write, and edit files.
For general conversation, just respond in the user's language."""

    example_messages = []
