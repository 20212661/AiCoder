"""edit_file — SEARCH/REPLACE 文件编辑工具"""
from ..spec import ToolSpec, ParamSpec

EDIT_FILE_SPEC = ToolSpec(
    name="edit_file",
    description="Replace a section of a file using exact text matching. Use this to make targeted changes to existing files.",
    parameters=[
        ParamSpec(name="path", required=True,
                  description="The file path relative to workspace root.",
                  usage="src/main.py"),
        ParamSpec(name="search", required=True,
                  description="The exact text to find in the file. Must match including whitespace and indentation.",
                  usage="old code block"),
        ParamSpec(name="replace", required=True,
                  description="The replacement text.",
                  usage="new code block"),
    ],
    instruction="The SEARCH text must match exactly, including all whitespace, comments, and indentation. If editing a new file, leave SEARCH empty and provide the full file content in REPLACE.",
)
