# AiCoder 工具系统整合可行性报告

> 基于 Cline 工具调用架构分析，针对 AiCoder v0.6.0 的整合方案
> 日期：2026-04-28

---

## 一、现状分析

### 1.1 当前"工具"是什么

AiCoder 没有显式的工具定义系统。LLM 通过系统提示词被告知输出特定文本格式，解析器从文本中提取操作意图：

| 操作类型 | LLM 输出格式 | 解析器 | 是否执行 |
|----------|-------------|--------|---------|
| 文件编辑（diff） | `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` 块 | `editblock_coder.py:find_original_update_blocks()` | 是 |
| 文件编辑（whole） | 代码围栏 + 文件名 | `wholefile_coder.py:get_edits()` | 是 |
| Shell 命令 | ` ```bash ` 代码块 | `editblock_coder.py:find_original_update_blocks()` | **否（被丢弃）** |
| 架构师规划 | 自然语言描述 | `architect_coder.py:reply_completed()` → 生成新 Coder | 间接 |

### 1.2 关键缺陷

| 缺陷 | 影响 |
|------|------|
| Shell 命令解析后丢弃，从未执行 | LLM 无法运行命令、读取输出 |
| 三种 Coder 各有独立解析器，无共享抽象 | 新增工具需修改多个文件 |
| 提示词硬编码在各 `*_prompts.py` 中 | 无法动态生成或按模型适配 |
| 无工具调用反馈循环（除 reflection） | LLM 难以从失败中恢复 |
| 无工具审批机制 | 所有编辑直接应用，无安全检查点 |

---

## 二、Cline 模式 vs AiCoder 现状 对照

```
Cline 架构                          AiCoder 现状
─────────────────────────────────────────────────────────
ToolSpec (结构化定义)               ❌ 无，散落在 prompts + parser
  ├─ 多模型变体                     ❌ 无
  ├─ XML 文本 + Native JSON Schema   ❌ 仅 XML 文本嵌入
  └─ PromptBuilder 自动生成提示词    ❌ 手动维护 *_prompts.py

Parser (统一解析)
  ├─ parseAssistantMessageV2()       ❌ 三种 Coder 各有独立解析器
  └─ ToolUse 统一中间格式            ❌ 无统一中间格式

ToolExecutor + Coordinator           ❌ 无协调层
  ├─ IToolHandler 接口               ❌ 逻辑内嵌在 coder.apply_edits()
  ├─ 审批流程                        ❌ 无 LLM 工具审批
  └─ Pre/Post hooks                  ❌ 无

pushToolResult()                     ❌ 仅 reflection 机制
  └─ 结构化 tool_result              ❌ 简单字符串拼接
```

---

## 三、建议整合项（按优先级）

### P0 — 立即执行，高收益低风险

#### 3.1 补全 Shell 命令执行链路

**现状**：`editblock_coder.py` 正确解析了 LLM 输出的 ` ```bash ` 块，存入 `self.shell_commands` 后即被丢弃。Aider 源项目有执行步骤，此 fork 移除了。

**方案**：在 `base_coder.send_message()` 中，`process_response()` 之后、`auto_commit()` 之前，增加 shell 命令执行步骤：

```python
for cmd in self.shell_commands:
    if self.io.confirm_ask(f"Run: {cmd.strip()[:80]}?"):
        result = subprocess.run(cmd, shell=True, ...)
        self.cur_messages.append(dict(
            role="user",
            content=f"Command result:\n{result.stdout}\n{result.stderr}"
        ))
```

**影响文件**：仅 `base_coder.py` (~15 行新增)
**风险**：需确认 `subprocess` 安全性（已在上轮修复了 shell 注入）

#### 3.2 工具规范化：ToolSpec → 提示词生成

**现状**：`editblock_prompts.py`、`wholefile_prompts.py`、`architect_prompts.py` 各自手动维护提示词文本。添加新工具需同时更新提示词（告诉 LLM 怎么输出）和解析器（提取 LLM 输出）。

**方案**：新增 `aicoder/tools/` 模块，每个工具一个 spec：

```python
# aicoder/tools/spec.py
@dataclass
class ToolSpec:
    name: str                    # "edit_file", "run_shell"
    description: str
    parameters: list[ParamSpec]
    xml_example: str             # LLM 输出的示例格式
    prompt_section: str          # 注入系统提示词的文本

@dataclass 
class ParamSpec:
    name: str
    required: bool
    description: str

# aicoder/tools/edit_file.py
EDIT_FILE_SPEC = ToolSpec(
    name="edit_file",
    description="Replace a section of a file using SEARCH/REPLACE blocks",
    parameters=[
        ParamSpec("path", True, "The file path to edit"),
        ParamSpec("search", True, "The exact text to find"),
        ParamSpec("replace", True, "The replacement text"),
    ],
    xml_example="""path/to/file.py
<<<<<<< SEARCH
old content
=======
new content
>>>>>>> REPLACE""",
    prompt_section="""## edit_file
Description: Replace a section of a file...
Parameters:
- path: (required) The file path
- search: (required) Exact text to find
- replace: (required) Replacement text
Usage:
<<<<<<< SEARCH
..."""
)
```

然后 `PromptBuilder` 从 `ToolSpec` 列表自动生成系统提示词的"工具"章节，替换当前手工维护的 `system_reminder`。

**影响文件**：新增 `aicoder/tools/` 目录（3-5 个文件）、修改 `base_coder.py:format_messages()` 调用 `PromptBuilder`
**收益**：新增工具只需定义 spec → 自动生成提示词 → 复用解析逻辑

### P1 — 建议执行，中等收益

#### 3.3 工具执行器 + 协调器模式

**方案**：参考 Cline 的 `ToolExecutor` + `ToolExecutorCoordinator` 模式：

```python
# aicoder/tools/executor.py
class ToolExecutor:
    def __init__(self, coordinator: ToolCoordinator):
        self.coordinator = coordinator

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        handler = self.coordinator.get(tool_call.name)
        if not handler:
            return ToolResult.error(f"Unknown tool: {tool_call.name}")
        # 审批检查（如果工具需要）
        if handler.requires_approval:
            approved = await self.request_approval(tool_call)
            if not approved:
                return ToolResult.rejected()
        return await handler.execute(tool_call)

# aicoder/tools/handlers/edit_file.py
class EditFileHandler(ToolHandler):
    name = "edit_file"

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        result = do_replace(
            tool_call.params["path"],
            read_file(tool_call.params["path"]),
            tool_call.params["search"],
            tool_call.params["replace"],
        )
        if result:
            write_file(tool_call.params["path"], result)
            return ToolResult.ok(f"Applied edit to {tool_call.params['path']}")
        return ToolResult.error(
            f"SEARCH block not found in {tool_call.params['path']}",
            suggestions=find_similar_lines(...)
        )

# aicoder/tools/handlers/shell.py
class ShellHandler(ToolHandler):
    name = "run_shell"

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        result = subprocess.run(
            tool_call.params["command"],
            shell=True, capture_output=True, text=True
        )
        return ToolResult.ok(
            f"Exit code: {result.returncode}\n{result.stdout}"
        )
```

**收益**：
- 每个工具独立 handler，职责清晰
- 审批流程统一（`requires_approval` 属性）
- 结果格式化统一（`ToolResult` 对象 → 标准化文本）

**风险**：重构现有 `apply_edits()` 逻辑，需保留模糊匹配算法

#### 3.4 结构化工具结果反馈

**方案**：用 `ToolResult` 对象替代当前的字符串拼接：

```python
@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: str
    error: Optional[str] = None
    suggestions: Optional[str] = None  # "did you mean?"

    def to_message(self) -> dict:
        """转为发给 LLM 的消息格式"""
        if self.success:
            return {"role": "user", "content": f"[{self.tool_name}] OK:\n{self.output}"}
        return {"role": "user", "content": f"[{self.tool_name}] FAILED:\n{self.error}"}
```

**收益**：LLM 能区分成功/失败，自主决定下一步；替代当前简陋的 `reflected_message` 机制

### P2 — 低优先级，长期可考虑

#### 3.5 多模型变体支持

Cline 为不同 `ModelFamily` 定义工具变体。当 AiCoder 需要支持更多模型（Claude、GPT、Gemini）且它们的工具调用能力不同时才有价值。当前只有 DeepSeek → 不需要。

#### 3.6 Native Tool Calling

当模型原生支持 function calling 时，直接发送 JSON Schema 而非嵌入文本提示词。收益是解析更可靠（无需模糊匹配 SEARCH 块），但目前 DeepSeek 的原生 tool calling 支持有限。

---

## 四、实施路线图

```
Phase 1 (本周) ─────────────────────
├─ P0.1: 补全 Shell 命令执行
│   修改 base_coder.py send_message() 流程
│   增加审批确认 + subprocess 执行
│
└─ P0.2: ToolSpec → 提示词生成
    新增 aicoder/tools/spec.py
    迁移 editblock/wholefile/shell 的提示词到 ToolSpec

Phase 2 (下周) ─────────────────────
├─ P1.1: 工具执行器 + 协调器
│   新增 ToolExecutor + ToolCoordinator
│   重构 apply_edits() 为 EditFileHandler
│   新增 ShellHandler（替换当前内联 subprocess）
│
└─ P1.2: 结构化 ToolResult
    新增 ToolResult 数据类
    替换 reflected_message 拼接逻辑

Phase 3 (未来) ─────────────────────
├─ P2.1: 多模型变体（当需要支持 Claude/GPT 时）
└─ P2.2: Native Tool Calling（当 DeepSeek 原生函数调用成熟时）
```

---

## 五、风险评估

| 风险 | 概率 | 缓解措施 |
|------|------|---------|
| 重构导致 SEARCH/REPLACE 匹配回退 | 中 | 保留现有 `do_replace()` 和模糊匹配算法不变，仅改变调用方式 |
| Shell 命令执行引入安全漏洞 | 中 | 已在上轮将 `shell=True` 改为 `shlex.split()`，新增审批弹窗 |
| ToolSpec 提示词质量不如手写 | 低 | 保留手工微调能力，ToolSpec 生成的是"基准"，可被 CoderPrompts 覆盖 |
| 新增抽象层增加复杂度 | 低 | 当前 ~3500 行代码，增加 ~300 行抽象是合理的 |

---

## 六、结论

**建议执行 Phase 1（P0.1 + P0.2）**。这两个改动涉及文件少（~4 个文件，~100 行新增代码），直接解决当前最痛的两个问题（Shell 命令被丢弃、工具定义散落各处），为后续扩展奠定基础。

Phase 2 的价值在于长期可维护性——当前 3 个 Coder 各有一套重复的解析/执行逻辑，随着工具增多会越来越难维护。但在工具数量 <5 的现阶段，收益不如 Phase 1 直接。
