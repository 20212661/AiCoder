"""Prompt builder with plan/act mode support"""
from .spec import ToolSpec


class PromptBuilder:

    HEADER = """# TOOL USE

You have access to tools that are executed upon your request.
Use XML tags to call them. Format:

<tool_name>
<param_name>value</param_name>
</tool_name>

Rules:
1. Use ONE tool at a time. Wait for the result before calling the next tool.
2. Never assume the result of a tool call.
3. If a tool fails, read the error and adjust your approach.
"""

    WORKING_DIR_RULE = """# WORKING DIRECTORY

Your working directory is: {cwd}
You CANNOT change directories. All paths must be relative to this directory.
All commands run from this directory.
"""

    PLAN_MODE_SECTION = """# PLAN MODE

You are currently in PLAN MODE. In this mode:
- You CAN use read-only tools: read_file, search_files, list_files, list_code_defs, run_shell
- You CANNOT use write tools: edit_file, write_file (they will be blocked)
- Focus on: gathering information, analyzing code, architecting solutions
- When you have a plan, present it clearly and wait for user feedback
- The user will switch to ACT MODE when ready to execute
"""

    ACT_MODE_SECTION = """# ACT MODE

You are in ACT MODE. All tools are available.
Execute the plan, modify files, and run commands as needed.
"""

    def __init__(self, tools: list[ToolSpec]):
        self._tools = tools
        self._model_list = []
        self._current_model = ""
        self._os_info = ""
        self._cwd = ""
        self._mode = "act"

    def set_models(self, model_list, current):
        self._model_list = model_list
        self._current_model = current

    def set_os_info(self, info):
        self._os_info = info

    def set_cwd(self, cwd):
        self._cwd = cwd

    def set_mode(self, mode):
        self._mode = mode

    def generate(self):
        sections = [self.HEADER]
        if self._cwd:
            sections.append(self.WORKING_DIR_RULE.format(cwd=self._cwd))
        if self._os_info:
            sections.append(self._os_info)
        # 模式指令
        if self._mode == "plan":
            sections.append(self.PLAN_MODE_SECTION)
        else:
            sections.append(self.ACT_MODE_SECTION)
        sections.append(self._model_section())
        for tool in self._tools:
            sections.append(self._tool_section(tool))
        return "\n".join(sections)

    def _model_section(self):
        if not self._model_list:
            return ""
        lines = ["# AVAILABLE MODELS", ""]
        lines.append("Current model: " + self._current_model)
        lines.append("")
        lines.append("Available models (switch with /model <name>):")
        for m in sorted(self._model_list):
            marker = " <== CURRENT" if m == self._current_model else ""
            lines.append("  - " + m + marker)
        lines.append("")
        return "\n".join(lines)

    def _tool_section(self, tool):
        lines = ["## " + tool.name, "Description: " + tool.description, ""]
        if tool.instruction:
            lines.append("Instructions: " + tool.instruction)
            lines.append("")
        if tool.parameters:
            lines.append("Parameters:")
            for p in tool.parameters:
                desc = p.prompt_line()
                if self._cwd and self._is_path_param(p.name):
                    desc += " (Working directory: " + self._cwd + ")"
                lines.append(desc)
            lines.append("")
        lines.append("Usage:")
        lines.append("<" + tool.name + ">")
        for p in tool.parameters:
            uv = p.usage or ("<" + p.name + ">")
            lines.append("<" + p.name + ">" + uv + "</" + p.name + ">")
        lines.append("</" + tool.name + ">")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _is_path_param(name):
        return name in ("path", "file_path", "directory")
