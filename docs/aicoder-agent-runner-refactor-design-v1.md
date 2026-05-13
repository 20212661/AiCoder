# AiCoder Agent Runner 重构设计文档 v1

## 1. 文档目标

本文档定义 AiCoder 下一阶段的 Agent Runner 重构方案。目标不是推翻现有 `Coder.run() -> AgentRuntime -> graph` 主链，而是在已完成“架构收口”的基础上，继续把运行时演进为：

- 单一主链
- 策略分层
- Step 可观测
- 可兼容多种模型工具调用协议
- 可恢复、可调试、可扩展

本文档参考了 Dify Agent Runner 的源码设计，但只吸收适合 AiCoder 的结构性思路，不直接复制其实现。

---

## 2. 当前现状

AiCoder 当前已经完成以下基础收口：

- 后端唯一主链：`Coder.run()` → `AgentRuntime.run_user_turn()` → LangGraph
- 前端唯一正式运行时：`official-ink`
- 模式语义单一事实源：`mode_definitions.py`

当前主链虽然已经统一，但运行时仍然存在以下结构性短板：

1. `AgentRuntime` 仍偏薄，但策略层尚未正式抽象
2. 工具调用输出解析尚未形成独立 parser 层
3. 每轮执行过程缺少统一的 step 数据模型
4. 历史重建仍以 message 为中心，而不是以“完整推理轮次”为中心
5. 目前主路径本质上仍只有一条 CoT/文本工具调用轨道，未正式支持 Function Calling 策略

---

## 3. 重构目标

本次重构目标分为五类。

### 3.1 结构目标

- 将“模式”和“策略”解耦
- 将“运行时骨架”和“具体工具调用协议”解耦
- 将“事件输出”和“聊天文本输出”解耦

### 3.2 能力目标

- 同时支持 CoT 文本工具调用 和 Function Calling 原生工具调用
- 每轮执行都具备统一的 `thought -> action -> observation -> final` 表达
- 支持基于 step 的历史重建与恢复

### 3.3 可观测性目标

- 前端可稳定展示 Agent 每轮执行过程
- 后端可稳定持久化每轮执行状态
- 故障排查不再依赖零散日志拼接

### 3.4 安全目标

- 保留现有 `sniff / plan / act` 权限边界
- 保留现有审批系统
- 保留最大轮次限制，并加入“最后一轮禁用工具”的强收口机制

### 3.5 非目标

- 不重写整个工具系统
- 不替换 LangGraph
- 不在本阶段引入复杂数据库迁移方案
- 不要求一步完成 UI 全量改造

---

## 4. 设计原则

1. 模式定义只负责“权限与行为边界”，不负责“模型调用协议”
2. Runner 策略只负责“如何让模型思考并调用工具”，不负责模式判断
3. Parser 层只负责“解释模型输出”，不负责执行工具
4. StepStore 只负责“记录与恢复”，不负责 prompt 拼接
5. 历史截断以“完整轮次”为单位，而不是任意 message 片段

---

## 5. 总体架构

建议将 AiCoder Agent 运行时演进为以下结构：

```text
User Input
  ↓
Coder.run()
  ↓
AgentAppRunner
  ↓
RunnerFactory
  ├─ CotAgentRunner
  └─ FunctionCallingAgentRunner
       ↓
   BaseAgentRunner
       ├─ AgentStepStore
       ├─ AgentHistoryRebuilder
       ├─ AgentHistoryTruncator
       ├─ ToolSchemaBuilder
       └─ AgentEventEmitter
```

同时保留现有：

- `mode_definitions.py`
- `permission_modes.py`
- `tools/executor.py`
- `graph/*`

但调整其职责边界。

---

## 6. 新分层设计

## 6.1 AgentAppRunner

### 职责

- 作为 Agent 执行入口编排层
- 根据模型能力和配置选择具体 runner 策略
- 统一创建执行上下文

### 不负责

- 不负责 prompt 拼装细节
- 不负责 parser
- 不负责工具执行

### 建议位置

- `aicoder/agent_app_runner.py`

### 核心接口

```python
class AgentAppRunner:
    def run_user_turn(self, coder, user_input: str) -> str | None:
        ...
```

### 选择策略

建议策略判断：

```python
if model_supports_function_calling and prefer_function_calling:
    runner = FunctionCallingAgentRunner(...)
else:
    runner = CotAgentRunner(...)
```

注意：`mode` 不参与 runner 策略选择。

---

## 6.2 BaseAgentRunner

### 职责

承载所有 runner 公共能力：

- tool schema 初始化
- agent step 创建与更新
- 历史重建
- 历史截断
- 公共状态收尾
- 统一事件发射

### 建议位置

- `aicoder/runners/base_agent_runner.py`

### 关键字段

```python
class BaseAgentRunner:
    coder: Coder
    session_id: str
    mode: str
    root: str
    model: Model
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    step_store: AgentStepStore
    event_emitter: AgentEventEmitter
```

### 公共方法

- `_init_prompt_tools()`
- `_create_step()`
- `_update_step_after_parse()`
- `_update_step_after_tool()`
- `_finalize_step()`
- `_build_history_messages()`
- `_truncate_history_messages()`
- `_emit_step_event()`

---

## 6.3 CotAgentRunner

### 职责

- 承载 CoT / ReAct 风格循环
- 使用文本/XML/JSON 工具调用协议
- 调用独立 parser 解析模型输出

### 建议位置

- `aicoder/runners/cot_agent_runner.py`

### 核心流程

```text
1. 初始化工具 schema
2. while step <= max_steps:
   - 创建 step
   - 组装 prompt
   - 调用 LLM 流
   - 交给 CotOutputParser 消费
   - 解析 thought/action
   - 更新 step
   - 若 final -> 收尾
   - 若 tool call -> 执行工具，记录 observation
   - 进入下一轮
3. 最终输出答案
```

### 关键改进

- 不在 runner 内手写输出解析
- 不让 `run()` 变成超长函数
- 最后一轮禁用工具

---

## 6.4 FunctionCallingAgentRunner

### 职责

- 承载原生 `tool_calls` 模式
- 直接消费模型结构化工具调用
- 不走 CoT 文本 action 解析

### 建议位置

- `aicoder/runners/function_calling_agent_runner.py`

### 核心流程

```text
1. 初始化结构化 tools schema
2. while step <= max_steps:
   - 创建 step
   - 组装 chat messages
   - invoke_llm(tools=..., stream=...)
   - 提取 tool_calls
   - 更新 step
   - 无 tool_calls 且有文本 -> final
   - 有 tool_calls -> 逐个执行工具
   - 记录 observation 并进入下一轮
3. 返回最终答案
```

### 与 CoT 的关键差异

- 不使用 `CotOutputParser`
- 不需要 `thought/action:` 文本协议
- 依赖模型能力检测

---

## 7. AgentStep 统一模型

这是本次重构的核心。

### 7.1 目标

统一表达每一轮执行过程，替代当前散落在：

- `tool_observations`
- `cur_messages`
- 前端 tool cards
- 零散事件通知

中的执行状态。

### 7.2 建议数据结构

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class AgentStep:
    id: str
    session_id: str
    iteration: int
    mode: str
    runner_type: Literal["cot", "function-calling"]
    phase: str = "created"
    thought: str = ""
    action_name: str | None = None
    action_input: dict | str | None = None
    action_raw: str | None = None
    observation: str = ""
    final_answer: str = ""
    tool_meta: dict = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    error: str = ""
    status: Literal[
        "created",
        "parsed",
        "observed",
        "final",
        "error",
    ] = "created"
```

### 7.3 状态流转

```text
created
  ↓
parsed
  ├─ final
  ├─ observed
  └─ error
```

### 7.4 StepStore 职责

建议新增：

- `aicoder/agent_step_store.py`

接口：

```python
class AgentStepStore:
    def create_step(...) -> AgentStep: ...
    def update_step_after_parse(...) -> None: ...
    def update_step_after_tool(...) -> None: ...
    def finalize_step(...) -> None: ...
    def load_steps(session_id: str) -> list[AgentStep]: ...
```

### 7.5 第一阶段存储方案

先不引入独立数据库表，先挂在现有 session 持久化结构中。

优点：

- 风险小
- 实现快
- 足够支持恢复、调试、UI 展示

---

## 8. Parser 分层设计

## 8.1 目标

把工具调用输出解析从 graph / runner 中抽离出来，形成独立层。

## 8.2 建议结构

```text
aicoder/parsers/
  ├─ base.py
  ├─ cot_json_action_parser.py
  ├─ cot_xml_tool_parser.py
  └─ function_call_parser.py
```

## 8.3 统一输出事件

```python
@dataclass
class ParserEvent:
    kind: Literal["text", "thought", "action", "final", "error"]
    text: str = ""
    action_name: str | None = None
    action_input: dict | str | None = None
    raw: str = ""
```

## 8.4 CotJsonActionParser

### 吸收 Dify 的点

- 字符级流式解析
- 花括号深度计数判断 JSON 完整性
- 代码块内 JSON 提取
- 残留缓存的容错收尾

### 明确不照搬的点

- 不用裸变量堆状态
- 不强依赖 `action:` / `thought:` 文本前缀
- 不把普通文本与结构化动作逻辑强耦合

### 建议内部状态对象

```python
@dataclass
class JsonParseState:
    in_code_block: bool = False
    in_json: bool = False
    brace_depth: int = 0
    code_block_cache: str = ""
    json_cache: str = ""
    text_cache: str = ""
```

## 8.5 FunctionCallParser

职责很简单：

- 从模型返回的 `tool_calls` 结构里提取
- 输出统一 `ParserEvent(kind="action", ...)`

这能让 CoT Runner 和 FC Runner 的下游 step 更新逻辑尽量一致。

---

## 9. History 重建与截断

## 9.1 目标

从“以聊天消息为中心”转向“以完整执行轮次为中心”。

## 9.2 新组件

建议新增：

- `aicoder/agent_history_rebuilder.py`
- `aicoder/agent_history_truncator.py`

## 9.3 AgentHistoryRebuilder

职责：

- 从 `done_messages + steps` 重建 prompt history
- CoT 输出成 scratchpad 风格文本
- FC 输出成 assistant/tool message 对

接口：

```python
class AgentHistoryRebuilder:
    def build_for_cot(...) -> list[dict]: ...
    def build_for_fc(...) -> list[dict]: ...
```

## 9.4 AgentHistoryTruncator

职责：

- 基于 token 预算截断历史
- 保留系统消息
- 保留最近完整轮次
- 不切断一半的 tool call / observation

接口：

```python
class AgentHistoryTruncator:
    def truncate(messages: list[dict], max_tokens: int, token_fn) -> list[dict]:
        ...
```

## 9.5 截断策略

建议借鉴 Dify：

1. 系统消息永远保留
2. 从最近轮次向前保留
3. 每次加入一个完整 iteration
4. 超限时丢弃该 iteration 整组

---

## 10. ToolSchemaBuilder 设计

## 10.1 目标

统一生成：

- CoT prompt 用的工具描述
- FC runner 用的结构化 tool schema

## 10.2 建议位置

- `aicoder/tool_schema_builder.py`

## 10.3 接口

```python
class ToolSchemaBuilder:
    def build_text_tools(self, tool_registry, mode: str) -> str: ...
    def build_prompt_message_tools(self, tool_registry, mode: str) -> list[dict]: ...
```

## 10.4 好处

- prompt 生成与 tool registry 解耦
- FC runner 不必自己拼 schema
- system prompt 和 FC tools 参数来源一致

---

## 11. AgentEventEmitter 设计

## 11.1 目标

将现有零散事件升级为统一的 step 事件流。

## 11.2 事件类型

建议新增统一事件：

- `agent.step.created`
- `agent.step.thought`
- `agent.step.action`
- `agent.step.observation`
- `agent.step.final`
- `agent.step.error`

## 11.3 建议位置

- `aicoder/agent_events.py`

## 11.4 前端收益

前端未来可以统一消费 step 流，而不是继续拼：

- `stream/token`
- `tool/call_started`
- `tool/call_finished`
- `tool/output`

这样可以更自然地做：

- 推理时间线
- step 折叠展开
- 失败定位
- 恢复回放

---

## 12. 与现有 graph 的关系

本次重构不要求移除 LangGraph。

建议关系如下：

- graph 继续负责状态推进和模式分支
- runner 负责具体策略执行细节
- graph 可以把“模型调用节点”委托给 runner

也就是说，未来不是：

- 用 runner 替换 graph

而是：

- 用 runner 让 graph 内部的“模型执行节点”更干净、更可替换

---

## 13. 模式与策略解耦规则

明确规则如下：

### 模式负责

- 工具可见性
- 工具执行权限
- shell 安全边界
- 提示词语义边界

### 策略负责

- 工具调用协议
- 模型输出解析协议
- prompt 组织方式
- tool result 注入方式

### 不允许

- `sniff` 决定是否走 CoT
- `plan` 决定是否走 FC
- `act` 决定 parser 类型

---

## 14. 错误处理策略

借鉴 Dify 的方向，但做更明确的落地。

## 14.1 工具错误

工具错误统一收敛为：

- 可读 observation
- step.error
- 可选 meta.error_type

工具错误不应直接让整个 runner 崩溃，除非：

- session 状态损坏
- critical internal invariant 被破坏

## 14.2 parser 错误

parser 错误应：

1. 尝试降级为普通文本
2. 若无法降级，则记录 step.error
3. 根据策略决定是否中止本轮

## 14.3 最大轮次

建议引入 Dify 风格的收口机制：

1. 正常轮次允许工具
2. 最后一轮移除 tools
3. 强制模型给出 final answer
4. 若仍未收口，抛出明确的 `AgentMaxIterationError`

---

## 15. 分阶段实施方案

建议分四期实施。

## Phase 1：Step 基础设施

### 范围

- 新增 `AgentStep`
- 新增 `AgentStepStore`
- 新增最小 step 事件

### 验收

- 每轮至少能创建并更新 step
- 前端可看到最小 step 流

## Phase 2：Parser 分层

### 范围

- 抽离工具调用解析逻辑
- 引入 `CotJsonActionParser`
- 引入统一 `ParserEvent`

### 验收

- 现有 CoT 工具调用不回归
- parser 可独立测试

## Phase 3：Runner 双策略

### 范围

- 引入 `BaseAgentRunner`
- 实现 `CotAgentRunner`
- 实现 `FunctionCallingAgentRunner`
- 入口按模型能力选 runner

### 验收

- 至少一个支持 tool_calls 的模型可走 FC
- 现有默认模型仍可走 CoT

## Phase 4：History 与恢复

### 范围

- 引入 history rebuilder / truncator
- 基于 step 恢复上下文
- 完整轮次截断

### 验收

- session 恢复时可重建 step 语义
- 长上下文下截断结果更稳定

---

## 16. 建议文件布局

```text
aicoder/
  agent_app_runner.py
  agent_step_store.py
  agent_events.py
  agent_history_rebuilder.py
  agent_history_truncator.py
  tool_schema_builder.py
  runners/
    base_agent_runner.py
    cot_agent_runner.py
    function_calling_agent_runner.py
  parsers/
    base.py
    cot_json_action_parser.py
    cot_xml_tool_parser.py
    function_call_parser.py
```

---

## 17. 与现有代码的映射关系

### 保留

- `mode_definitions.py`
- `permission_modes.py`
- `tools/executor.py`
- `graph/*`
- `rpc_io.py`
- `official-ink` 前端

### 逐步迁移

- `AgentRuntime`：从执行主体迁移为编排适配层
- `message_builder.py`：逐步把历史重建职责迁出
- 现有工具调用解析逻辑：迁移到 parser 层

### 未来可删除或降级

- 与旧 edit format 强绑定的后处理残留
- 零散 tool event 拼装逻辑

---

## 18. 风险与控制

### 风险 1：一次改太大

控制：

- 严格按四期拆
- 每期先补结构，再补 UI

### 风险 2：CoT 现有行为回归

控制：

- Phase 2 之前不改主 runner 语义
- 先把 parser 抽离，保持行为等价

### 风险 3：FC 模式引入兼容性问题

控制：

- 仅对明确支持 tool_calls 的模型启用
- 保留 CoT 作为默认保底

### 风险 4：历史恢复混乱

控制：

- 先做 step 持久化
- 再做 history rebuild
- 不要两者同时重写

---

## 19. 最小验收标准

本设计落地后的最小可验收标准：

1. AiCoder 具备正式的 runner 分层
2. 每轮执行有统一 `AgentStep`
3. 输出解析器可独立测试
4. CoT 与 FC 至少存在两条清晰策略路径
5. 历史截断以完整轮次为单位
6. 前端可消费统一 step 事件流

---

## 20. 结论

AiCoder 当前已经完成“主链统一”，下一阶段最值得投入的是“策略分层 + step 可观测 + parser 独立 + history 轮次化”。

从 Dify 借鉴的核心不是复杂类层次本身，而是：

- Runner 分层
- Step 持久化
- 输出解析独立
- 完整轮次历史
- 事件驱动可观测

建议从 Phase 1 开始推进，不要直接跳到 Function Calling 全量落地。对 AiCoder 而言，最有性价比的第一步是先引入 `AgentStep` 与 `AgentStepStore`，这样后续 parser、runner、history、UI 都会有稳定依托。
