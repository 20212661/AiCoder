"""list_code_defs — 列出代码定义（类/函数/方法）"""
from ..spec import ToolSpec, ParamSpec

LIST_CODE_DEFS_SPEC = ToolSpec(
    name="list_code_defs",
    description="List top-level code definitions (classes, functions, methods) in a directory. Uses tree-sitter to parse source code. Useful for understanding a module's API without reading all its files.",
    parameters=[
        ParamSpec(name="path", required=True,
                  description="Directory path relative to workspace root. Must be a directory, not a file.",
                  usage="src/"),
    ],
    instruction="Shows definition names from up to 50 source files. Only extracts top-level definitions — not nested or private ones.",
)
