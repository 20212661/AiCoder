"""ToolHandler 基类 — 对照 Cline 的 IToolHandler"""
from ..result import ToolCall, ToolResult


class ToolHandler:
    """工具处理器基类

    子类必须覆盖:
      - name: str       — 工具名
      - execute()        — 执行逻辑

    子类可覆盖:
      - requires_approval: bool  — 是否需要用户审批（默认 True）
      - validate_params()        — 参数验证（默认检查 required params）
      - description()            — 人类可读的描述
    """
    name: str = ""
    requires_approval: bool = True

    def validate_params(self, tool_call: ToolCall) -> str:
        """验证参数完整性。返回空字符串表示通过，否则返回错误信息。"""
        # 从注册的 ToolSpec 中读取 required 参数列表（如果可用）
        missing = []
        for param_name in self._required_param_names():
            if not tool_call.get(param_name):
                missing.append(param_name)
        if missing:
            return f"Missing required parameters: {', '.join(missing)}"
        return ""

    def _required_param_names(self) -> list[str]:
        """从 ToolRegistry 获取当前工具的必填参数名"""
        return []

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        raise NotImplementedError(f"{self.name}.execute() not implemented")

    def description(self, tool_call: ToolCall) -> str:
        return f"[{self.name}]"
