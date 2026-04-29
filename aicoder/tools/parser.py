"""
XML 工具调用解析器 — 对照 Cline 的 parseAssistantMessageV2()

逐字符状态机，三态循环：
  A: 普通文本 → 检测 <toolname> 开标签 → B
  B: 工具标签内 → 检测 <param> 开标签 → C
  C: 参数值内 → 检测 </param> 闭标签 → B
  B → 检测 </toolname> 闭标签 → A
"""
from .result import ToolCall, TextBlock
from .registry import ToolRegistry


def parse_xml_tools(content: str, registry: ToolRegistry) -> list[ToolCall | TextBlock]:
    """解析 AI 回复中的 XML 工具调用，返回文本块和工具调用的混合列表"""
    if not content:
        return [TextBlock("")]

    tool_tags = {f"<{t.name}>": t.name for t in registry.get_all()}
    param_tags = registry.all_param_names

    blocks: list[ToolCall | TextBlock] = []
    current_text: list[str] = []
    current_tool: ToolCall | None = None
    current_param: str | None = None
    current_value: list[str] = []

    i = 0
    n = len(content)

    while i < n:
        matched = False

        # --- 检测工具开标签 ---
        if not current_tool:
            for tag, tool_name in tool_tags.items():
                if content.startswith(tag, i):
                    if current_text:
                        blocks.append(TextBlock("".join(current_text)))
                        current_text = []
                    current_tool = ToolCall(name=tool_name)
                    current_param = None
                    current_value = []
                    i += len(tag)
                    matched = True
                    break

        if matched:
            continue

        # --- 工具标签内：检测参数开标签 ---
        if current_tool and not current_param:
            for param_name in param_tags:
                tag = f"<{param_name}>"
                if content.startswith(tag, i):
                    current_param = param_name
                    current_value = []
                    i += len(tag)
                    matched = True
                    break

        if matched:
            continue

        # --- 参数值内：检测参数闭标签 ---
        if current_tool and current_param:
            close_tag = f"</{current_param}>"
            if content.startswith(close_tag, i):
                current_tool.params[current_param] = "".join(current_value)
                current_value = []
                current_param = None
                i += len(close_tag)
                matched = True

        if matched:
            continue

        # --- 检测工具闭标签 ---
        if current_tool and not current_param:
            close_tag = f"</{current_tool.name}>"
            if content.startswith(close_tag, i):
                blocks.append(current_tool)
                current_tool = None
                current_value = []
                i += len(close_tag)
                matched = True

        if matched:
            continue

        # --- 普通字符 ---
        ch = content[i]
        if current_param:
            current_value.append(ch)
        elif current_tool:
            # 工具标签内但在参数之外的空白字符，忽略
            pass
        else:
            current_text.append(ch)
        i += 1

    # 尾部文本
    if current_text:
        blocks.append(TextBlock("".join(current_text)))

    # 未闭合的工具调用：当作文本处理
    if current_tool:
        raw = _reconstruct_raw(content, current_tool)
        blocks.append(TextBlock(raw))

    return blocks


def _reconstruct_raw(content: str, tool: ToolCall) -> str:
    """重建未闭合工具调用的原始文本"""
    parts = [f"<{tool.name}>"]
    for k, v in tool.params.items():
        parts.append(f"<{k}>{v}</{k}>")
    return "".join(parts)
