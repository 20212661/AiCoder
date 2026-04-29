"""list_files — 列出目录结构"""
from ..spec import ToolSpec, ParamSpec

LIST_FILES_SPEC = ToolSpec(
    name="list_files",
    description="List files and directories in a given path. After getting results, ALWAYS describe what you found — do NOT say you cannot see files.",
    parameters=[
        ParamSpec(name="path", required=True,
                  description="Directory path relative to workspace root.",
                  usage="src/"),
        ParamSpec(name="recursive", required=False,
                  description="Use true or false (default).",
                  usage="true"),
    ],
    instruction="Lists up to 200 files. IMPORTANT: After the result, summarize what you found.",
)
