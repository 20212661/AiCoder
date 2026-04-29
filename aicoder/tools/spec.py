"""工具定义数据类 — 对照 Cline 的 ClineToolSpec"""
from dataclasses import dataclass, field


@dataclass
class ParamSpec:
    """工具参数定义 — 对照 ClineToolSpecParameter"""
    name: str
    required: bool = True
    description: str = ""
    usage: str = ""

    def prompt_line(self) -> str:
        req = "(required)" if self.required else "(optional)"
        return f"- {self.name}: {req} {self.description}"


@dataclass
class ToolSpec:
    """工具定义 — 对照 ClineToolSpec"""
    name: str
    description: str
    parameters: list[ParamSpec] = field(default_factory=list)
    instruction: str = ""

    @property
    def param_names(self) -> list[str]:
        return [p.name for p in self.parameters]

    def required_params(self) -> list[ParamSpec]:
        return [p for p in self.parameters if p.required]
