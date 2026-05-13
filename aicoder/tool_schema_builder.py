"""Unified tool schema generation for CoT and Function Calling runners.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §10
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aicoder.mode_definitions import get_visible_tools

if TYPE_CHECKING:
    from aicoder.tools.registry import ToolRegistry


class ToolSchemaBuilder:
    """Generate tool descriptions for both CoT prompt text and FC structured schema."""

    @staticmethod
    def build_text_tools(tool_registry: ToolRegistry, mode: str) -> str:
        """Build the XML tool-use description text for CoT system prompts.

        Delegates to SystemPrompt._tool_use() to avoid duplicating logic.
        """
        from aicoder.tools.system_prompt import SystemPrompt

        visible = get_visible_tools(mode)
        tools = [t for t in tool_registry.get_all() if t.name in visible]

        sp = SystemPrompt()
        sp.configure(tools=tools, cwd="", os_name="", model_list=[], current_model="", mode=mode, ai_identity="")
        return sp._tool_use()

    @staticmethod
    def build_prompt_message_tools(tool_registry: ToolRegistry, mode: str) -> list[dict]:
        """Build OpenAI-compatible tools schema for Function Calling runners."""
        visible = get_visible_tools(mode)
        tools = [t for t in tool_registry.get_all() if t.name in visible]

        result = []
        for tool in tools:
            properties = {}
            required = []
            for p in tool.parameters:
                properties[p.name] = {"type": "string", "description": p.description}
                if p.required:
                    required.append(p.name)

            result.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return result
