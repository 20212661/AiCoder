# AiCoder XML 工具调用系统设计报告

> 参考 Cline XML 模式，为 AiCoder 构建可扩展的工具调用架构
> 日期：2026-04-28

---

## 一、从 Cline 到 AiCoder：对照映射

### 1.1 核心组件映射

| Cline 组件 | AiCoder 对应 | 当前状态 |
|-----------|-------------|---------|
| `ClineToolSpec` | `ToolSpec` dataclass | 不存在 |
| `tools/*.ts` (每工具一文件) | `aicoder/tools/*.py` | 不存在 |
| `init.ts` register | `registry.py` | 不存在 |
| `PromptBuilder.tool()` | `PromptBuilder.generate()` | 不存在 |
| `parseAssistantMessageV2()` | `parser.py: parse_xml_tools()` | 需新增（替代各 Coder 独立解析器） |
| `ToolUse` 对象 | `ToolCall` dataclass | 不存在 |
| `ToolExecutor` + `ToolExecutorCoordinator` | `executor.py` + `coordinator.py` | 不存在 |
| `IToolHandler` + `ExecuteCommandToolHandler` | `handlers/*.py` | 不存在 |
| `pushToolResult()` | `executor.push_result()` | 不存在 |
| `variants/*/config.ts` | 简化：单模型家族（DeepSeek），暂不需要变体 | N/A |

### 1.2 工具映射

| Cline 工具 | AiCoder 工具 | 说明 |
|-----------|-------------|------|
| `execute_command` | `run_shell` | 执行 Shell 命令 |
| `write_to_file` | `write_file` | WholeFile 模式的整文件写入 |
| `replace_in_file` | `edit_file` | EditBlock 模式的 SEARCH/REPLACE |
| `read_file` | `read_file` | 读取文件（当前通过 /add 手动） |
| `search_files` | `search_files` | 搜索文件内容（当前无） |
| `search_files` | `list_files` | 列出文件（当前 /ls 命令） |

---

## 二、架构设计

### 2.1 新目录结构

```
aicoder/
├── tools/                          # 新增：工具系统
│   ├── __init__.py
│   ├── spec.py                     # ToolSpec + ParamSpec 数据类
│   ├── registry.py                 # ToolRegistry：注册、查找、回退
│   ├── prompt_builder.py           # 从 ToolSpec 生成提示词文档
│   ├── parser.py                   # XML 逐字符解析器
│   ├── executor.py                 # ToolExecutor + ToolCoordinator
│   ├── result.py                   # ToolResult + ToolCall 数据类
│   ├── tools/                      # 工具定义（每个工具一个文件）
│   │   ├── edit_file.py            # SEARCH/REPLACE 编辑
│   │   ├── write_file.py           # 整文件写入
│   │   ├── run_shell.py            # Shell 命令执行
│   │   └── read_file.py            # 读取文件
│   └── handlers/                   # 工具执行器（每个工具一个文件）
│       ├── edit_file_handler.py    # SEARCH/REPLACE 处理
│       ├── write_file_handler.py   # 整文件写入处理
│       ├── run_shell_handler.py    # Shell 命令处理
│       └── read_file_handler.py    # 文件读取处理
```

### 2.2 ToolSpec 设计（对照 ClineToolSpec）

```python
# aicoder/tools/spec.py

@dataclass
class ParamSpec:
    """工具参数定义（对照 ClineToolSpecParameter）"""
    name: str                          # XML 标签名，如 "path"
    required: bool                     # 是否必填
    description: str                   # 参数说明文本
    usage: str = ""                    # XML 示例值（仅 XML 模式）
    type: str = "string"              # string | boolean | integer

@dataclass
class ToolSpec:
    """工具定义（对照 ClineToolSpec）"""
    name: str                          # XML 标签名，如 "edit_file"
    description: str                   # 工具描述（注入系统提示词）
    parameters: list[ParamSpec]        # 参数列表
    instruction: str = ""              # 附加使用说明
    xml_example: str = ""              # 完整 XML 调用示例
```

### 2.3 完整数据流（对照 Cline XML 模式）

```
启动时注册
  tools/*.py → registry.register()
       │
       ▼
构建系统提示词（每次 send_message 时）
  registry.get_all() → PromptBuilder.generate() → 嵌入 system_reminder
       │
       ▼
AI 输出 XML
  "我来修改文件。
   <edit_file>
   <path>src/main.py</path>
   <search>old code</search>
   <replace>new code</replace>
   </edit_file>"
       │
       ▼
XML 解析（逐字符状态机）
  parser.parse(xml_text) → [ToolCall(name="edit_file", params={...})]
       │
       ▼
工具执行
  executor.execute(tool_call) → coordinator.route() → handler.execute()
       │
       ▼
结果回传
  executor.push_result(tool_result) → 追加到 cur_messages
       │
       ▼
下一轮 API 调用
  LLM 看到工具结果，决定下一步
```

---

## 三、XML 解析器设计

### 3.1 核心算法（对照 parseAssistantMessageV2）

```python
# aicoder/tools/parser.py

def parse_xml_tools(content: str, tool_registry: ToolRegistry) -> list[ToolCall | TextBlock]:
    """逐字符解析 AI 回复中的 XML 工具调用。
    
    对照 Cline 的 parseAssistantMessageV2() 三态状态机：
    - 状态 A: 普通文本 → 检测 <toolname> → 进入状态 B
    - 状态 B: 工具标签内 → 检测 <param> → 进入状态 C
    - 状态 C: 参数值内 → 检测 </param> → 回到状态 B
    - 状态 B → 检测 </toolname> → 回到状态 A
    """
    # 预计算所有工具标签
    tool_tags = {f"<{t.name}>": t.name for t in tool_registry.get_all()}
    param_tags = {
        f"<{p.name}>": p.name
        for t in tool_registry.get_all()
        for p in t.parameters
    }
    
    blocks = []
    current_text = []
    current_tool = None      # 当前正在解析的工具
    current_param = None     # 当前正在解析的参数名
    current_value = []       # 当前参数值缓冲区
    
    i = 0
    while i < len(content):
        matched = False
        
        # 检查工具开标签
        for tag, tool_name in tool_tags.items():
            if content.startswith(tag, i):
                # 保存之前的文本块
                if current_text:
                    blocks.append(TextBlock("".join(current_text)))
                    current_text = []
                current_tool = ToolCall(tool_name)
                current_param = None
                i += len(tag)
                matched = True
                break
        
        if matched:
            continue
        
        # 检查参数开标签
        if current_tool:
            for tag, param_name in param_tags.items():
                if content.startswith(tag, i):
                    # 保存之前的参数值
                    if current_param and current_value:
                        current_tool.params[current_param] = "".join(current_value)
                        current_value = []
                    current_param = param_name
                    i += len(tag)
                    matched = True
                    break
        
        if matched:
            continue
        
        # 检查参数闭标签
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
        
        # 检查工具闭标签
        if current_tool:
            close_tag = f"</{current_tool.name}>"
            if content.startswith(close_tag, i):
                # 处理最后一个参数
                if current_param and current_value:
                    current_tool.params[current_param] = "".join(current_value)
                blocks.append(current_tool)
                current_tool = None
                current_param = None
                current_value = []
                i += len(close_tag)
                matched = True
        
        if matched:
            continue
        
        # 普通字符
        ch = content[i]
        if current_param:
            current_value.append(ch)
        elif current_tool:
            # 工具标签内的空白文本（忽略或收集为 text）
            pass
        else:
            current_text.append(ch)
        i += 1
    
    # 尾部文本
    if current_text:
        blocks.append(TextBlock("".join(current_text)))
    
    return blocks
```

### 3.2 解析示例

AI 输出：
```
我来修改文件。

<edit_file>
<path>src/main.py</path>
<search>print("hello")</search>
<replace>print("hey")</replace>
</edit_file>

修改完成。
```

解析结果：
```python
[
    TextBlock("我来修改文件。\n\n"),
    ToolCall(
        name="edit_file",
        params={
            "path": "src/main.py",
            "search": 'print("hello")',
            "replace": 'print("hey")',
        }
    ),
    TextBlock("\n\n修改完成。"),
]
```

---

## 四、提示词生成器设计

### 4.1 PromptBuilder（对照 Cline 的 PromptBuilder.tool()）

```python
# aicoder/tools/prompt_builder.py

class PromptBuilder:
    """从 ToolSpec 列表生成 AI 可读的工具文档"""
    
    @staticmethod
    def generate(tools: list[ToolSpec]) -> str:
        """生成完整的工具文档章节"""
        sections = [
            "# TOOL USE",
            "",
            "You have access to tools. Use XML tags to call them:",
            "",
            "<tool_name>",
            "<param_name>value</param_name>",
            "</tool_name>",
            "",
            "Always wait for the tool result before continuing.",
            "",
        ]
        
        for tool in tools:
            sections.append(PromptBuilder._tool_section(tool))
            sections.append("")
        
        sections.append(PromptBuilder._examples_section(tools))
        
        return "\n".join(sections)
    
    @staticmethod
    def _tool_section(tool: ToolSpec) -> str:
        """为单个工具生成文档（对照 Cline 的 ## tool_name 格式）"""
        lines = [
            f"## {tool.name}",
            f"Description: {tool.description}",
        ]
        
        if tool.instruction:
            lines.append(f"Instructions: {tool.instruction}")
        
        if tool.parameters:
            lines.append("Parameters:")
            for p in tool.parameters:
                req = "(required)" if p.required else "(optional)"
                lines.append(f"- {p.name}: {req} {p.description}")
        
        # Usage 示例
        lines.append("Usage:")
        lines.append(f"<{tool.name}>")
        for p in tool.parameters:
            usage_value = p.usage or f"<{p.name}_value>"
            lines.append(f"<{p.name}>{usage_value}</{p.name}>")
        lines.append(f"</{tool.name}>")
        
        return "\n".join(lines)
```

### 4.2 生成的提示词文档示例

```
# TOOL USE

You have access to tools. Use XML tags to call them:

<tool_name>
<param_name>value</param_name>
</tool_name>

Always wait for the tool result before continuing.

## edit_file
Description: Replace a section of a file using exact text matching.
Parameters:
- path: (required) The file path to edit, relative to workspace root.
- search: (required) The exact text to find in the file.
- replace: (required) The replacement text.
Usage:
<edit_file>
<path>src/main.py</path>
<search>old code</search>
<replace>new code</replace>
</edit_file>

## run_shell
Description: Execute a CLI command on the system.
Parameters:
- command: (required) The command to execute.
- requires_approval: (required) "true" if user should confirm, "false" otherwise.
Usage:
<run_shell>
<command>pytest tests/</command>
<requires_approval>true</requires_approval>
</run_shell>
```

---

## 五、执行器设计

### 5.1 ToolExecutor（对照 Cline 的 ToolExecutor）

```python
# aicoder/tools/executor.py

class ToolCoordinator:
    """路由工具调用到对应 Handler"""
    
    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}
    
    def register(self, handler: ToolHandler):
        self._handlers[handler.name] = handler
    
    def get(self, tool_name: str) -> Optional[ToolHandler]:
        return self._handlers.get(tool_name)

class ToolExecutor:
    """执行工具调用并管理结果"""
    
    def __init__(self, coordinator: ToolCoordinator, io, coder):
        self.coordinator = coordinator
        self.io = io
        self.coder = coder
    
    def execute_batch(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """执行一批工具调用，返回结果列表"""
        results = []
        for call in tool_calls:
            result = self._execute_one(call)
            results.append(result)
            # 把结果追加到对话
            self._push_result(call, result)
        return results
    
    def _execute_one(self, tool_call: ToolCall) -> ToolResult:
        handler = self.coordinator.get(tool_call.name)
        if not handler:
            return ToolResult.error(f"Unknown tool: {tool_call.name}")
        
        # 审批检查
        if handler.requires_approval:
            if not self._request_approval(tool_call):
                return ToolResult.rejected(tool_call.name)
        
        return handler.execute(tool_call, self.coder)
    
    def _push_result(self, tool_call: ToolCall, result: ToolResult):
        """把工具结果格式化为对话消息并追加"""
        self.coder.cur_messages.append(result.to_message())
```

### 5.2 ToolHandler 接口（对照 IToolHandler）

```python
class ToolHandler:
    """工具处理器基类"""
    name: str = ""
    requires_approval: bool = False
    
    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        raise NotImplementedError
    
    def description(self, tool_call: ToolCall) -> str:
        """生成人类可读的描述（如 "[edit_file for 'src/main.py']"）"""
        return f"[{self.name}]"
```

### 5.3 具体 Handler 示例

```python
# aicoder/tools/handlers/run_shell_handler.py

class RunShellHandler(ToolHandler):
    name = "run_shell"
    requires_approval = True
    
    def execute(self, tool_call, coder) -> ToolResult:
        command = tool_call.params.get("command", "")
        if not command:
            return ToolResult.error("Missing required parameter: command")
        
        try:
            result = subprocess.run(
                shlex.split(command),
                capture_output=True, text=True,
                cwd=coder.root, timeout=120,
            )
            if result.returncode == 0:
                return ToolResult.ok(self.name, result.stdout)
            return ToolResult.error(
                f"Exit code: {result.returncode}\n{result.stdout}\n{result.stderr}"
            )
        except subprocess.TimeoutExpired:
            return ToolResult.error("Command timed out (120s)")
        except Exception as e:
            return ToolResult.error(str(e))
```

---

## 六、与现有代码的集成路径

### 6.1 base_coder.py send_message() 改造

```python
# 改造前
def send_message(self, message):
    ...
    self.process_response()      # 各 Coder 子类分别解析
    ...

# 改造后
def send_message(self, message):
    ...
    # 1. XML 解析
    blocks = parse_xml_tools(
        self.partial_response_content,
        self.tool_registry
    )
    
    # 2. 提取工具调用
    tool_calls = [b for b in blocks if isinstance(b, ToolCall)]
    text_blocks = [b for b in blocks if isinstance(b, TextBlock)]
    
    # 3. 如果有工具调用，执行它们
    if tool_calls:
        results = self.tool_executor.execute_batch(tool_calls)
        # 结果已自动追加到 cur_messages
    else:
        # 无工具调用 → 纯文本回复
        pass
    
    # 4. 后处理
    ...
```

### 6.2 向后兼容策略

**阶段 1（本次）**：新增 `aicoder/tools/` 模块，同时保留现有 `*_coder.py` 解析逻辑。`format_messages()` 同时注入 XML 工具文档和传统 system_reminder。

**阶段 2（验证后）**：让 `base_coder.send_message()` 优先使用 XML 解析器；如果 XML 解析为空，回退到传统解析。

**阶段 3（稳定后）**：移除 `*_coder.py` 中的独立解析逻辑，全部走 `tools/parser.py`。

---

## 七、实施计划

### 本次实施范围

| 序号 | 文件 | 内容 | 行数估算 |
|------|------|------|---------|
| 1 | `aicoder/tools/__init__.py` | 模块初始化 | 5 |
| 2 | `aicoder/tools/spec.py` | ToolSpec + ParamSpec 数据类 | 40 |
| 3 | `aicoder/tools/registry.py` | ToolRegistry 注册/查找 | 40 |
| 4 | `aicoder/tools/result.py` | ToolCall + ToolResult + TextBlock | 50 |
| 5 | `aicoder/tools/prompt_builder.py` | 从 ToolSpec 生成提示词文档 | 60 |
| 6 | `aicoder/tools/parser.py` | XML 逐字符解析器 | 80 |
| 7 | `aicoder/tools/executor.py` | ToolExecutor + ToolCoordinator | 60 |
| 8 | `aicoder/tools/tools/edit_file.py` | edit_file 工具定义 | 30 |
| 9 | `aicoder/tools/tools/run_shell.py` | run_shell 工具定义 | 25 |
| 10 | `aicoder/tools/tools/write_file.py` | write_file 工具定义 | 25 |
| 11 | `aicoder/tools/handlers/edit_file_handler.py` | SEARCH/REPLACE 执行（复用现有 do_replace） | 40 |
| 12 | `aicoder/tools/handlers/run_shell_handler.py` | Shell 命令执行 | 30 |
| 13 | `aicoder/tools/handlers/write_file_handler.py` | 整文件写入 | 30 |
| 14 | `aicoder/coders/base_coder.py` | 集成：注入工具文档到 system prompt，新 send_message 流程 | +30 |
| **合计** | **14 个文件** | | **~545 行新增** |

---

## 八、关键决策

1. **AI 输出格式**：采用 Cline 的纯 XML 标签格式（`<tool_name><param>value</param></tool_name>`），不引入 JSON。原因是 XML 格式与 LLM 的自然语言输出共存更好（文本 + XML 标签混排），且不需要 JSON Schema 的校验开销。

2. **参数类型均为字符串**：对照 Cline 的设计，`ToolCall.params` 的所有值都是 `str`。`requires_approval` 的 `"true"/"false"`、数字等由 handler 内部转换。这与 SEARCH/REPLACE 的当前模式一致（所有内容都是文本）。

3. **保留 SEARCH/REPLACE 匹配算法**：`edit_file_handler.py` 内部直接调用现有的 `do_replace()` 和模糊匹配算法，不重写。

4. **不引入变体系统**：当前只有 DeepSeek 一个模型家族，不需要 Cline 的 `ModelFamily` 多变体机制。未来支持多模型时再引入。
