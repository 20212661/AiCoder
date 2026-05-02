"""
插件/扩展系统

允许用户自定义工具和命令，支持：
- 装饰器注册：@tool_plugin, @command_plugin
- 自动发现：内置工具 + ~/.aicoder/plugins/ 用户插件
- 零配置：插件放到目录即可被发现

使用示例：

    # ~/.aicoder/plugins/my_tool.py
    from aicoder.plugins import tool_plugin, ToolSpec, ParamSpec, ToolHandler, ToolResult, ToolCall

    @tool_plugin(
        spec=ToolSpec(
            name="my_tool",
            description="A custom tool",
            parameters=[ParamSpec(name="input", description="Input text")],
        )
    )
    class MyToolHandler(ToolHandler):
        name = "my_tool"
        requires_approval = False

        def execute(self, tool_call: ToolCall, coder) -> ToolResult:
            return ToolResult.ok(self.name, tool_call.params.get("input", ""))
"""

from .loader import PluginLoader, plugin_registry

__all__ = [
    "PluginLoader",
    "plugin_registry",
]