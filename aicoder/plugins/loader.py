"""
插件加载器 — 注册表模式 + 装饰器自动发现

核心类：
- PluginRegistry：全局注册表，存储工具 spec、handler、命令
- PluginLoader：自动发现并加载 ~/.aicoder/plugins/ 下的插件
- @tool_plugin / @command_plugin：装饰器，用于注册自定义扩展
"""
import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from ..tools.spec import ToolSpec
from ..tools.handlers.base import ToolHandler

logger = logging.getLogger(__name__)


class PluginRegistry:
    """全局插件注册表 — 存储工具和命令扩展"""

    def __init__(self):
        self._tool_plugins: dict[str, tuple[ToolSpec, type[ToolHandler]]] = {}
        self._command_plugins: dict[str, Callable] = {}
        self._loaded: bool = False

    # ---- 工具注册 ----

    def register_tool(self, spec: ToolSpec, handler_cls: type[ToolHandler]) -> None:
        """注册一个工具插件（spec + handler 配对）"""
        name = spec.name
        if name in self._tool_plugins:
            logger.warning("Plugin tool %r already registered, overwriting", name)
        self._tool_plugins[name] = (spec, handler_cls)

    def get_tool_specs(self) -> list[ToolSpec]:
        """返回所有已注册的工具 spec"""
        return [spec for spec, _ in self._tool_plugins.values()]

    def get_tool_handler(self, name: str) -> Optional[type[ToolHandler]]:
        """按名称获取工具 handler 类"""
        entry = self._tool_plugins.get(name)
        return entry[1] if entry else None

    def get_tool_handlers(self) -> list[type[ToolHandler]]:
        """返回所有已注册的工具 handler 类"""
        return [cls for _, cls in self._tool_plugins.values()]

    # ---- 命令注册 ----

    def register_command(self, name: str, func: Callable) -> None:
        """注册一个斜杠命令插件

        Args:
            name: 命令名（不含 /），如 "my-cmd"
            func: 命令处理函数，签名为 func(commands, args: str) -> None
        """
        if name in self._command_plugins:
            logger.warning("Plugin command /%s already registered, overwriting", name)
        self._command_plugins[name] = func

    def get_commands(self) -> dict[str, Callable]:
        """返回所有已注册的命令 {name: handler}"""
        return dict(self._command_plugins)

    # ---- 状态 ----

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def clear(self) -> None:
        """清空所有注册（主要用于测试）"""
        self._tool_plugins.clear()
        self._command_plugins.clear()
        self._loaded = False


# 全局单例
plugin_registry = PluginRegistry()


# ---- 装饰器 ----

def tool_plugin(spec: ToolSpec):
    """装饰器：将 ToolHandler 子类注册为工具插件

    用法::

        @tool_plugin(spec=ToolSpec(
            name="my_tool",
            description="Does something cool",
            parameters=[ParamSpec(name="input", description="Input text")],
        ))
        class MyToolHandler(ToolHandler):
            name = "my_tool"

            def execute(self, tool_call, coder):
                return ToolResult.ok(self.name, "done")
    """
    def decorator(cls: type[ToolHandler]) -> type[ToolHandler]:
        plugin_registry.register_tool(spec, cls)
        # 确保 handler.name 与 spec.name 一致
        if not getattr(cls, "name", None):
            cls.name = spec.name
        return cls
    return decorator


def command_plugin(name: str):
    """装饰器：将函数注册为斜杠命令插件

    用法::

        @command_plugin("hello")
        def hello_command(commands, args: str):
            commands.io.tool_output(f"Hello, {args}!")
    """
    def decorator(func: Callable) -> Callable:
        plugin_registry.register_command(name, func)
        return func
    return decorator


# ---- 自动发现 ----

PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".aicoder", "plugins")


class PluginLoader:
    """从文件系统自动发现和加载用户插件"""

    def __init__(self, registry: Optional[PluginRegistry] = None):
        self._registry = registry or plugin_registry

    def load_all(self, plugin_dir: Optional[str] = None) -> int:
        """扫描插件目录，加载所有 .py 文件

        Args:
            plugin_dir: 插件目录路径，默认 ~/.aicoder/plugins/

        Returns:
            成功加载的插件数量
        """
        if self._registry.is_loaded:
            return 0

        search_dir = plugin_dir or PLUGIN_DIR
        if not os.path.isdir(search_dir):
            self._registry._loaded = True
            return 0

        loaded = 0
        for filename in sorted(os.listdir(search_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            filepath = os.path.join(search_dir, filename)
            module_name = f"aicoder_plugin_{filename[:-3]}"

            try:
                self._load_module(module_name, filepath)
                loaded += 1
                logger.info("Loaded plugin: %s", filename)
            except Exception as exc:
                logger.warning("Failed to load plugin %s: %s", filename, exc)

        self._registry._loaded = True
        return loaded

    def _load_module(self, module_name: str, filepath: str) -> None:
        """动态加载一个 Python 模块文件"""
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {filepath}")
        module = importlib.util.module_from_spec(spec)
        # 注册到 sys.modules 以支持相对导入
        sys.modules[module_name] = module
        spec.loader.exec_module(module)