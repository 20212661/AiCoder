# aiCoder v1.2 实现级任务拆解
版本：v1.2
目标读者：执行型编码 Agent（如 GLM）
执行要求：强约束、按阶段提交、每阶段必须可运行、可测试、可回退

---

## 0. 本版目标

v1.2 只做 4 件事：

1. 在现有 `AgentStepStore` 之上，引入轻量 `EventLog-Lite`
2. 建立 `History View`，把 UI 日志 / Runtime 历史 / LLM 上下文三层分离
3. 引入第一版 `Condensation Pipeline`
4. 把 tool/action/observation 从“以字符串为主”升级为“结构化事件为主”

---

## 1. 强约束

### 1.1 必须遵守
1. 不允许移除 LangGraph 主链
2. 不允许删除现有 `ModeConfig / ContextPacker / MessageConversion`
3. 不允许破坏 v1.1 已通过的 FC / CoT 双路径
4. 不允许把 event 层直接做成完整数据库事件溯源大重构
5. 不允许一次性替换掉 `AgentStepStore`，必须渐进演进
6. 所有新增逻辑必须优先通过新增模块接入
7. `ContextPacker` 仍然必须是唯一上下文组装入口
8. `Condensation` 不允许直接改写原始历史，必须生成派生视图或摘要块
9. UI 日志层、Runtime 历史层、LLM 上下文层必须明确区分职责
10. 每个阶段都必须补测试

### 1.2 暂时禁止
1. 禁止引入完整数据库 schema 重构
2. 禁止引入复杂 subagent DAG 编排
3. 禁止重写 RPC / TUI 协议
4. 禁止全面迁移 tree-sitter repo map
5. 禁止为了压缩历史而删除核心调试信息

### 1.3 代码风格要求
1. 所有新增事件类型必须是结构化 dataclass / TypedDict
2. 不允许继续把 observation 的主要语义藏在自由文本里
3. 所有“给 LLM 的上下文”必须由 history view 生成
4. 所有“给 UI 的日志”必须能独立于 LLM context 存在
5. conversion / projection / condensation 必须分模块，不能写成一个大文件

---

## 2. 完成定义

当 v1.2 完成时，系统必须满足：

1. 存在轻量事件模型 `AgentEventRecord`
2. 一轮中多个 tool call / tool result 能自然记录为多个事件
3. `History View` 可生成三种视图：
   - UI view
   - runtime history view
   - llm context view
4. `ContextPacker` 不再直接只吃原始 `done_messages`，而是优先消费 history view
5. 存在第一版 `Condensation Pipeline`
6. 长历史可被摘要块替换，而不是只靠简单裁剪
7. FC / CoT 都能消费 condensed history
8. `ToolObservation` 与失败信息以结构化 payload 为主
9. v1.1 的核心能力不回归
10. 测试通过

---

## 3. 目录级改造方案

### 3.1 新增文件

新增以下文件：

- `aicoder/events/__init__.py`
- `aicoder/events/types.py`
- `aicoder/events/store.py`
- `aicoder/events/projector.py`
- `aicoder/context/history_view.py`
- `aicoder/context/condense.py`
- `aicoder/tests/test_event_store.py`
- `aicoder/tests/test_history_view.py`
- `aicoder/tests/test_condense.py`
- `aicoder/tests/test_event_observation.py`

### 3.2 允许扩展的现有文件

- `aicoder/agent_step_store.py`
- `aicoder/graph/nodes.py`
- `aicoder/context/packer.py`
- `aicoder/messages/conversion.py`
- `aicoder/tools/result.py`
- `aicoder/graph/state.py`

---

## 4. 分阶段实施

---

# 阶段 1：引入 EventLog-Lite

## 4.1 目标
在不推翻 v1.1 的前提下，新增轻量事件记录层，为后续 history view 和 condensation 提供结构化输入。

## 4.2 要做的事

### 新建 `aicoder/events/types.py`
定义最小事件结构：

```python
from dataclasses import dataclass, field
from typing import Any, Literal
import time

EventKind = Literal[
    "user_message",
    "assistant_text",
    "assistant_thought",
    "tool_call",
    "tool_result",
    "tool_error",
    "step_started",
    "step_finished",
    "summary_inserted",
    "compaction_applied",
]

@dataclass
class AgentEventRecord:
    event_id: str
    session_id: str
    iteration: int
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
```

要求：
1. 先不要过度设计
2. `payload` 必须结构化
3. 不允许只存一段大字符串当 payload

### 新建 `aicoder/events/store.py`
实现一个轻量内存事件仓：

```python
class AgentEventStore:
    def append(...)
    def append_many(...)
    def list_events(...)
    def events_for_iteration(...)
    def last_event(...)
```

要求：
1. 与 `AgentStepStore` 一样先做内存版
2. API 要稳定，后续可替换为持久化实现

### 修改 `aicoder/agent_step_store.py`
要求：
1. 先不要删除 `AgentStepStore`
2. 增加对 `event_store` 的组合或挂接能力
3. 在 step 生命周期关键点写入事件：
   - create_step -> `step_started`
   - parse -> `assistant_thought` / `tool_call`
   - tool success -> `tool_result`
   - tool failure -> `tool_error`
   - finalize -> `step_finished`

最小方案允许：
- `AgentStepStore` 内部持有 `AgentEventStore`
- 暂时由 step store 代理写事件

### 修改 `aicoder/runners/base_agent_runner.py`
在这些地方补事件：
- `_create_step()`
- `_update_step_after_parse()`
- `_update_step_after_tool()`
- `_finalize_step()`
- `_mark_step_error()`

要求：
- 不要只写 step，不写 event
- 事件内容要足够支撑后续 history view

## 4.3 必须新增测试
新增 `aicoder/tests/test_event_store.py`

覆盖：
1. append / list / last_event 正常
2. step 生命周期会产生对应事件
3. 多 tool calls 情况下能记录多个 `tool_call`
4. tool success / tool failure 事件 payload 正确

## 4.4 验收标准
1. 存在可用的 `AgentEventStore`
2. 主路径会产生事件
3. 事件不是测试里手工构造，而是运行时真实产生
4. 测试通过

---

# 阶段 2：引入 History View

## 5.1 目标
把“原始历史数据”和“不同消费方看到的历史”分开。

## 5.2 要做的事

### 新建 `aicoder/context/history_view.py`
定义三种视图函数：

- `build_ui_history_view(coder, mode, runner_type) -> list[dict]`
- `build_runtime_history_view(coder, mode, runner_type) -> list[dict]`
- `build_llm_history_view(coder, mode, runner_type) -> list[dict]`

要求：
1. UI view：
   - 可以保留 step started / finished / verbose 信息
2. runtime history view：
   - 保留结构化 action / observation
3. llm history view：
   - 只保留喂给模型需要的内容
   - 必须尽量精简

### 优先复用 v1.1 能力
要求：
- FC 路径继续复用 `runner.build_history_messages()` 或 `AgentHistoryRebuilder`
- CoT 路径保持兼容
- 不允许在 history view 里重新发明一套完全重复的 FC / CoT 转换逻辑

### 修改 `aicoder/context/packer.py`
要求：
1. `pack_context()` 不再直接从 `done_messages` 生拼历史
2. 改为优先调用 `build_llm_history_view(...)`
3. `history_override` 可以保留，但要弱化为底层兼容机制
4. 不允许让 `ContextPacker` 同时承担“事件读取 + 视图生成 + 转换 + 压缩”全部职责

### 修改 `aicoder/graph/nodes.py`
要求：
- `_build_llm_messages()` 仍调用 `pack_context()`
- 但历史内容必须来自 history view，而不是散落来源

## 5.3 必须新增测试
新增 `aicoder/tests/test_history_view.py`

覆盖：
1. UI / runtime / llm 三种视图输出不同
2. FC 视图保留结构化 tool_calls / tool messages
3. CoT 视图保留文本 observation
4. UI view 可包含 LLM 不需要的事件
5. `ContextPacker` 已消费 `build_llm_history_view()`

## 5.4 验收标准
1. 三种视图函数存在且主路径接入
2. `ContextPacker` 不再只是“拼 done_messages”
3. 测试通过

---

# 阶段 3：引入 Condensation Pipeline（第一版）

## 6.1 目标
对长历史建立“prune -> summarize -> replace”的第一版压缩链。

## 6.2 要做的事

### 新建 `aicoder/context/condense.py`
实现以下结构：

```python
from dataclasses import dataclass

@dataclass
class CondensedBlock:
    summary: str
    covered_event_ids: list[str]
    kind: str = "summary_block"
```

必须提供函数：

- `prune_history_events(events: list[AgentEventRecord], mode: str) -> list[AgentEventRecord]`
- `summarize_history_events(events: list[AgentEventRecord], coder=None) -> CondensedBlock | None`
- `apply_condensation_to_history_view(history_view: list[dict], condensed: CondensedBlock | None) -> list[dict]`

### 第一版策略要求

#### prune
至少做到：
1. 对旧 `tool_result` 正文做瘦身
2. 保留：
   - tool_name
   - success/failure
   - summary
   - files
   - recommended_next
3. 不要直接删掉整条工具记录

#### summarize
第一版可以先不用 LLM，允许先做模板摘要：
- Goal
- Findings
- Actions Taken
- Failures
- Files Touched
- Next Step

如果你要接 LLM 摘要，也必须保留 deterministic fallback。

#### replace
要求：
- 在 llm history view 中，用摘要块替换旧事件
- 原始事件仍保留在 event store 中
- 不允许原地销毁原始历史

### 修改 `aicoder/context/history_view.py`
要求：
- `build_llm_history_view()` 接入 condense pipeline
- 仅对 llm view 应用 condensation
- UI view / runtime view 默认保留更多原始信息

## 6.3 必须新增测试
新增 `aicoder/tests/test_condense.py`

覆盖：
1. prune 后旧 tool result 正文被缩短，但摘要仍保留
2. summarize 能生成固定结构块
3. apply_condensation 不会破坏最近消息
4. 只对 llm history view 生效
5. 原始事件未丢失

## 6.4 验收标准
1. 存在可运行的 condense pipeline
2. LLM 上下文已使用 condensation 结果
3. UI / runtime 历史未被错误压平
4. 测试通过

---

# 阶段 4：升级 Tool / Observation 结构化表达

## 7.1 目标
让 tool 调用和结果不再主要靠自由文本语义，而以结构化 payload 为主。

## 7.2 要做的事

### 修改 `aicoder/graph/state.py`
扩展 `ToolObservation`：

至少增加：
- `tool_call_id`
- `error_type`
- `summary`
- `recommended_next`
- `files`
- `iteration`

### 修改 `aicoder/tools/result.py`
增强 `ToolResult.meta`

要求：
- success / fail / blocked / rejected 都尽量写出统一字段
- 至少标准化：
  - `tool_name`
  - `success`
  - `rejected`
  - `error_type`
  - `summary`
  - `files`
  - `recommended_next`

### 修改 `aicoder/graph/nodes.py`
在：
- `permission_node()`
- `execute_tool_node()`
- `observe_tool_result()`

要求：
1. observation payload 以结构化字段为主
2. 文本内容只是渲染视图，不是唯一语义来源
3. tool failure 必须可被 condense pipeline 使用
4. FC / CoT 两条路径都要能读取这些结构化 observation

## 7.3 必须新增测试
新增 `aicoder/tests/test_event_observation.py`

覆盖：
1. permission deny 产生结构化 observation
2. tool success 产生结构化 observation
3. tool failure 产生结构化 observation
4. FC / CoT 都能消费这些 observation
5. condensation 可读取 `summary / files / recommended_next`

## 7.4 验收标准
1. observation 不再依赖自由文本为唯一真相
2. event payload 足够支撑 condensation
3. 测试通过

---

# 阶段 5：把 History View 与 Context Budget 打通

## 8.1 目标
让预算限制作用在 history view / condensed view 上，而不是只作用在原始消息列表。

## 8.2 要做的事

### 修改 `aicoder/context/policies.py`
保留现有 budget，但明确分层含义：
- `history_tokens`
- `focused_file_tokens`
- `tool_trace_tokens`
- `repo_map_tokens`

### 修改 `aicoder/context/packer.py`
要求：
1. `history_tokens` 作用于 `llm history view`
2. `tool_trace_tokens` 至少有初版实现：
   - 超预算时优先裁剪旧工具 trace 的正文
3. `focused_file_tokens` 暂时可只加 TODO，但要有明确挂点
4. 不允许预算逻辑再次散落到 graph node

## 8.3 必须新增测试
修改：
- `aicoder/tests/test_context_packer.py`

新增覆盖：
1. condensation 后 history budget 仍生效
2. `tool_trace_tokens` 能影响旧工具 trace 的保留程度
3. FC / CoT 在 budget 下都能正常工作

## 8.4 验收标准
1. budget 已作用在 history view 上
2. `tool_trace_tokens` 至少有初版效果
3. 测试通过

---

## 5. 具体文件修改清单

### 必改文件
- `aicoder/agent_step_store.py`
- `aicoder/context/packer.py`
- `aicoder/context/policies.py`
- `aicoder/graph/nodes.py`
- `aicoder/graph/state.py`
- `aicoder/messages/conversion.py`
- `aicoder/tools/result.py`
- `aicoder/runners/base_agent_runner.py`

### 新增文件
- `aicoder/events/__init__.py`
- `aicoder/events/types.py`
- `aicoder/events/store.py`
- `aicoder/events/projector.py`
- `aicoder/context/history_view.py`
- `aicoder/context/condense.py`
- `aicoder/tests/test_event_store.py`
- `aicoder/tests/test_history_view.py`
- `aicoder/tests/test_condense.py`
- `aicoder/tests/test_event_observation.py`

---

## 6. 提交粒度要求

GLM 必须按以下粒度提交修改：

1. `feat: add lightweight agent event store`
2. `feat: add history view separation for ui runtime llm`
3. `feat: add first condensation pipeline`
4. `feat: enrich structured tool observation payloads`
5. `refactor: apply context budget on llm history view`

每一步都要：
- 修改代码
- 跑测试
- 输出变更说明
- 当前阶段通过后再进入下一阶段

---

## 7. 每阶段完成后的测试命令

优先运行：

```bash
pytest aicoder/tests/test_event_store.py
pytest aicoder/tests/test_history_view.py
pytest aicoder/tests/test_condense.py
pytest aicoder/tests/test_event_observation.py
pytest aicoder/tests/test_context_packer.py
pytest aicoder/tests/test_message_conversion.py
pytest aicoder/tests/test_unified_loop.py
```

阶段性回归：

```bash
pytest aicoder/tests/ -x
```

如果时间较长，至少运行：

```bash
pytest aicoder/tests/test_event_store.py aicoder/tests/test_history_view.py aicoder/tests/test_condense.py aicoder/tests/test_context_packer.py
```

---

## 8. GLM 输出要求

每完成一个阶段，必须输出：

```md
## 阶段 N 完成报告

### 已完成
- ...

### 修改文件
- ...

### 核心实现
- ...

### 测试结果
- 运行命令：
- 通过情况：

### 风险与兼容性
- ...

### 下一阶段建议
- ...
```

---

## 9. 禁止性提醒

GLM 不允许做以下事情：

1. 不要删除 v1.1 的核心模块
2. 不要把 `AgentStepStore` 直接删掉
3. 不要只加 event 类型但不接主路径
4. 不要把 condensation 做成“删消息”
5. 不要把 UI view 和 llm view 混成一份
6. 不要只在测试里手工调用 history view / condense 假装主链接好了
7. 不要把 observation 继续主要藏在字符串里
8. 不要破坏 FC / CoT 差异
9. 不要引入大依赖
10. 不要顺手扩散到 TUI / RPC 大改

---

## 10. 实施顺序总结

严格按这个顺序做：

1. EventLog-Lite
2. History View
3. Condensation Pipeline
4. Observation 结构化升级
5. Budget 与 History View 打通

不得跳序，除非当前阶段被代码现实阻塞，并在报告中明确说明原因。

---

## 11. 最终交付标准

完成后必须满足：

1. 运行时真实产生结构化事件
2. 存在 UI / runtime / llm 三种历史视图
3. LLM 上下文由 history view + condensation 生成
4. 多工具调用能自然进入事件流
5. 旧工具结果可被裁剪但不丢语义
6. FC / CoT 都能消费 condensed history
7. v1.1 能力不回归
8. 测试通过
