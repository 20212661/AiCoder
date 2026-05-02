"""
System Prompt 生成器 — 对照 Cline 的 12 段模块化系统提示词

每段用 ==== 分隔，分固定和动态两部分。
所有动态数据通过 configure() 注入。
"""
from .spec import ToolSpec


class SystemPrompt:
    """对标 Cline 的 12 段系统提示词装配器"""

    SEP = "\n\n====\n\n"

    def __init__(self):
        self._tools: list[ToolSpec] = []
        self._cwd = ""
        self._os_name = ""
        self._model_list: list[str] = []
        self._current_model = ""
        self._mode = "act"
        self._ai_identity = ""

    def configure(self, tools, cwd, os_name, model_list, current_model, mode, ai_identity):
        self._tools = tools
        self._cwd = cwd
        self._os_name = os_name
        self._model_list = model_list
        self._current_model = current_model
        self._mode = mode
        self._ai_identity = ai_identity

    def build(self):
        sections = [
            self._agent_role(),
            self._tool_use(),
            self._editing_files(),
            self._act_vs_plan(),
            self._capabilities(),
            self._rules(),
            self._system_info(),
            self._objective(),
        ]
        return self.SEP.join(s for s in sections if s)

    # ══════ 第 1 段：身份 ══════
    def _agent_role(self):
        identity = self._ai_identity or "You are an expert software developer and AI pair programming assistant."
        return identity

    # ══════ 第 2 段：工具系统 ══════
    def _tool_use(self):
        parts = []
        # 格式说明
        parts.append("""# TOOL USE

You have access to tools executed upon your request.
Use XML tags to call them:

<tool_name>
<param_name>value</param_name>
</tool_name>""")
        # 每个工具的定义
        for tool in self._tools:
            parts.append(self._tool_def(tool))
        # 使用准则
        parts.append("""# Tool Use Guidelines

1. Use ONE tool at a time. Wait for the result before calling the next.
2. Never assume the result of a tool call — always read the actual output.
3. If a tool fails, read the error message and adjust your approach.
4. Prefer read-only tools (read_file, search_files, list_files) to explore before editing.
5. After list_files, ALWAYS describe what you found to the user.""")
        return "\n\n".join(parts)

    def _tool_def(self, tool):
        lines = ["## " + tool.name, "Description: " + tool.description]
        if tool.instruction:
            lines.append("Instructions: " + tool.instruction)
        if tool.parameters:
            lines.append("Parameters:")
            for p in tool.parameters:
                req = "(required)" if p.required else "(optional)"
                desc = f"- {p.name}: {req} {p.description}"
                if self._cwd and self._is_path_param(p.name):
                    desc += " (Working directory: " + self._cwd + ")"
                lines.append(desc)
        lines.append("Usage:")
        lines.append("<" + tool.name + ">")
        for p in tool.parameters:
            uv = p.usage or ("<" + p.name + ">")
            lines.append("<" + p.name + ">" + uv + "</" + p.name + ">")
        lines.append("</" + tool.name + ">")
        return "\n".join(lines)

    @staticmethod
    def _is_path_param(name):
        return name in ("path", "file_path", "directory")

    # ══════ 第 3 段：编辑策略 ══════
    def _editing_files(self):
        return """# EDITING FILES

You have two tools for modifying files:

edit_file — For targeted changes. Use SEARCH to find exact text and REPLACE to change it.
  Best for: small fixes, refactoring, updating specific sections.
  The SEARCH text must match exactly, including whitespace and indentation.

write_file — For creating new files or rewriting entire files.
  Best for: new files, major rewrites, when the file doesn't exist yet.

Strategy: Prefer edit_file for existing files (only changes what's needed).
Use write_file when creating from scratch or when most of the file is changing."""

    # ══════ 第 4 段：模式 ══════
    def _act_vs_plan(self):
        if self._mode == "plan":
            return """# PLAN MODE

You are in PLAN MODE. In this mode:
- You CAN use read-only tools: read_file, search_files, list_files, list_code_defs, run_shell
- You CANNOT use write tools: edit_file, write_file (they will be blocked)
- Focus on gathering information, analyzing code, and architecting solutions
- When you have a plan, present it clearly and wait for user feedback
- The user will switch to ACT MODE when ready to execute"""
        else:
            return """# ACT MODE

You are in ACT MODE. All tools are available.
Execute the plan, modify files, and run commands as needed.
After completing a task, summarize what you did."""

    # ══════ 第 5 段：能力 ══════
    def _capabilities(self):
        lines = ["# CAPABILITIES", ""]
        lines.append("You can:")
        lines.append("- Read any file with read_file (line numbers included)")
        lines.append("- Search code with search_files (regex, file pattern filtering)")
        lines.append("- List directory contents with list_files (recursive option)")
        lines.append("- Extract code definitions with list_code_defs (functions, classes, methods)")
        lines.append("- Run shell commands with run_shell (Windows: use dir not ls)")
        lines.append("- Edit files precisely with edit_file (SEARCH/REPLACE)")
        lines.append("- Create or overwrite files with write_file")
        lines.append("")
        lines.append("The project file tree is provided in the first message.")
        if self._model_list:
            lines.append("Use /model <name> to switch between available models.")
        return "\n".join(lines)

    # ══════ 第 6 段：行为规则 ══════
    def _rules(self):
        rules = [
            "Your working directory is fixed. All paths are relative to it.",
            "Do not use ~ or $HOME in paths.",
            "Use Windows commands (dir, type, findstr) when on Windows.",
            "Prefer list_files over run_shell for directory listing.",
            "Always read a file before editing it.",
            "After each tool call, wait for the result before proceeding.",
            "Do not ask unnecessary questions — use tools to find answers.",
            "When asked about available models, list them from the system prompt.",
            "For casual conversation, respond briefly in the user's language.",
            "Do NOT start responses with 'Great!', 'Certainly!', 'Okay!' or 'Sure!'.",
            "Keep SEARCH blocks concise — just the changing lines plus context.",
            "If a tool fails, read the error carefully and adjust.",
        ]
        return "# RULES\n\n" + "\n".join("- " + r for r in rules)

    # ══════ 第 7 段：系统信息 ══════
    def _system_info(self):
        lines = ["# SYSTEM INFORMATION", ""]
        lines.append("Working directory: " + self._cwd)
        lines.append("Operating system: " + self._os_name)
        lines.append("")
        if self._model_list:
            lines.append("Available models:")
            for m in sorted(self._model_list):
                marker = " <== CURRENT" if m == self._current_model else ""
                lines.append("  " + m + marker)
        return "\n".join(lines)

    # ══════ 第 8 段：工作方法 ══════
    def _objective(self):
        return """# WORK METHODOLOGY

1. Understand the request — if something is unclear, ask a brief clarifying question.
2. Explore the codebase — use read_file, search_files, and list_files to gather context.
3. Form a plan — before editing, explain what you're going to do in 1-2 sentences.
4. Execute — use edit_file or write_file to make changes.
5. Verify — after editing, use run_shell to run tests or check syntax if applicable.
6. Summarize — briefly tell the user what you changed and why."""
