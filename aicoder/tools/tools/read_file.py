"""read_file — 读取文件内容，带行号和截断"""
from ..spec import ToolSpec, ParamSpec

READ_FILE_SPEC = ToolSpec(
    name="read_file",
    description="Read the contents of a file. Returns content with line numbers. Use start_line/end_line to read specific ranges.",
    parameters=[
        ParamSpec(name="path", required=True,
                  description="The file path relative to workspace root.",
                  usage="src/main.py"),
        ParamSpec(name="start_line", required=False,
                  description="Starting line number (1-based). Defaults to 1.",
                  usage="1"),
        ParamSpec(name="end_line", required=False,
                  description="Ending line number (1-based, inclusive). Defaults to reading 500 lines.",
                  usage="100"),
    ],
    instruction="Use this to read file contents before editing. If the file is large, use start_line and end_line to read specific sections.",
)
