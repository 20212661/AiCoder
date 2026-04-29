"""search_files — 正则搜索文件内容"""
from ..spec import ToolSpec, ParamSpec

SEARCH_FILES_SPEC = ToolSpec(
    name="search_files",
    description="Search file contents using a regular expression. Returns matching lines with file paths and line numbers.",
    parameters=[
        ParamSpec(name="path", required=True,
                  description="Directory to search in, relative to workspace root.",
                  usage="src/"),
        ParamSpec(name="regex", required=True,
                  description="Regular expression pattern to search for in file contents.",
                  usage="def main"),
        ParamSpec(name="file_pattern", required=False,
                  description="Optional glob pattern to filter files (e.g., '*.py', '*.ts').",
                  usage="*.py"),
    ],
    instruction="Use this to find where functions, classes, or patterns are defined or used before making edits.",
)
