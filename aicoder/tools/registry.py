"""工具注册表 — 对照 Cline 的 ClineToolSet"""
from .spec import ToolSpec


class ToolRegistry:
    """存储和查找所有已注册工具"""

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def get_all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    @property
    def all_param_names(self) -> set[str]:
        """收集所有工具的所有参数名，供解析器预计算标签"""
        names: set[str] = set()
        for tool in self._tools.values():
            for param in tool.parameters:
                names.add(param.name)
        return names
