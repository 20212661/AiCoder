"""
AiCoder 工具调用系统 — Cline XML 模式

架构：
  ToolSpec → PromptBuilder → 系统提示词中的工具文档
   AI XML 输出 → Parser → ToolCall → Executor → Handler → ToolResult
"""
from .spec import ToolSpec, ParamSpec
from .registry import ToolRegistry
from .result import ToolCall, ToolResult, TextBlock
from .prompt_builder import PromptBuilder
from .parser import parse_xml_tools
from .executor import ToolExecutor, ToolCoordinator
