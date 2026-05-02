"""
示例工具插件 — 将此文件复制到 ~/.aicoder/plugins/ 即可使用

功能：统计代码行数，通过 /count 或 AI 调用 count_lines 工具使用
"""
from aicoder.plugins.loader import tool_plugin, command_plugin
from aicoder.tools.spec import ToolSpec, ParamSpec
from aicoder.tools.handlers.base import ToolHandler
from aicoder.tools.result import ToolResult, ToolCall


@tool_plugin(spec=ToolSpec(
    name="count_lines",
    description="统计指定文件的代码行数（空行、注释行、代码行）",
    parameters=[
        ParamSpec(name="path", description="文件路径（相对于工作目录）"),
    ],
    instruction="使用此工具统计代码文件的行数分布。",
))
class CountLinesHandler(ToolHandler):
    name = "count_lines"
    requires_approval = False

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        import os
        path = tool_call.params.get("path", "")
        abs_path = coder.abs_root_path(path)

        if not os.path.isfile(abs_path):
            return ToolResult.fail(self.name, f"File not found: {path}")

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            return ToolResult.fail(self.name, f"Cannot read file: {e}")

        total = len(lines)
        blank = sum(1 for l in lines if not l.strip())
        comments = sum(1 for l in lines if l.strip().startswith("#"))
        code = total - blank - comments

        result = (
            f"File: {path}\n"
            f"  Total lines: {total}\n"
            f"  Code lines:  {code}\n"
            f"  Blank lines: {blank}\n"
            f"  Comment lines: {comments}"
        )
        return ToolResult.ok(self.name, result)


@command_plugin("count")
def count_command(commands, args: str):
    """统计文件行数 /count <file_path>"""
    path = args.strip()
    if not path:
        commands.io.tool_output("Usage: /count <file_path>")
        return

    import os
    abs_path = os.path.join(commands.coder.root, path)
    if not os.path.isfile(abs_path):
        commands.io.tool_error(f"File not found: {path}")
        return

    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total = len(lines)
    blank = sum(1 for l in lines if not l.strip())
    comments = sum(1 for l in lines if l.strip().startswith("#"))
    code = total - blank - comments

    commands.io.tool_output(
        f"  Total: {total}  |  Code: {code}  |  Blank: {blank}  |  Comments: {comments}"
    )