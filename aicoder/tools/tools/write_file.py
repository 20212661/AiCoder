"""write_file — 整文件写入工具"""
from ..spec import ToolSpec, ParamSpec

WRITE_FILE_SPEC = ToolSpec(
    name="write_file",
    description="Write or overwrite an entire file. Use this for creating new files or replacing the entire content of an existing file.",
    parameters=[
        ParamSpec(name="path", required=True,
                  description="The file path relative to workspace root.",
                  usage="src/new_module.py"),
        ParamSpec(name="content", required=True,
                  description="The complete file content.",
                  usage="import sys\n\ndef main():\n    ...\n"),
    ],
)
