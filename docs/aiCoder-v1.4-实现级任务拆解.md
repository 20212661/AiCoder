# aiCoder v1.4 实现级任务拆解
版本：v1.4
主题：Event Persistence / Replay / Resume
目标读者：执行型编码 Agent（如 GLM）
执行要求：强约束、按阶段提交、每阶段必须可运行、可测试、可回退

---

## 0. 本版目标

v1.4 只做 4 件事：

1. 让 `EventLog-Lite` 从内存层升级成可持久化事件层
2. 建立 `replay / resume` 能力
3. 让 `History View / Condensation / Debug` 消费持久化事件
4. 为以后真正的“长任务恢复”和“会话重放”打基础

---

## 1. 强约束

### 1.1 必须遵守
1. 不允许移除 LangGraph 主链
2. 不允许破坏 v1.3 已通过的 Mode / Context / Repo Context / Condensation / Debug 能力
3. 不允许删除现有 `AgentStepStore`，必须渐进演进
4. 不允许删除现有 `AgentEventStore` API，只能增强
5. replay 必须基于真实事件，而不是从最终消息猜状态
6. resume 必须优先从事件恢复，而不是只靠 `done_messages`
7. 持久化失败必须 graceful fallback，不允许主链直接崩
8. 每个阶段都必须补测试
9. 所有新 persistence / replay 能力必须可 debug / 可 dump

### 1.2 暂时禁止
1. 禁止一次性做完整数据库事件溯源系统
2. 禁止重写 RPC / TUI / 前端存储协议
3. 禁止做分布式任务编排
4. 禁止改 subagent 架构
5. 禁止顺手重写 repo context / condensation 主逻辑

### 1.3 代码风格要求
1. 持久化接口、事件模型、replay 逻辑必须模块化
2. 内存 store 与持久化 store 必须通过统一接口访问
3. replay 逻辑不能散落在 graph node 中
4. 不允许把恢复逻辑做成一堆隐式 side effect
5. 所有恢复路径必须可测试

---

## 2. 完成定义

当 v1.4 完成时，系统必须满足：

1. `AgentEventStore` 支持持久化到本地文件或轻量存储
2. 一个 session 的事件可被重新加载
3. 可基于事件流 replay 出 runtime history view / llm history view
4. 重新启动后，session 至少能恢复：
   - step 事件
   - tool_result / tool_error
   - condensation 输入历史
5. debug 工具可以查看 persisted events / replay 结果
6. v1.3 的主链和上下文能力不回归
7. 测试通过

---

## 3. 总体设计方向

本版不追求“完整事件溯源平台”，而是做一个足够稳的中间层：

1. 先定义统一 `EventStore` 接口
2. 保留现有内存实现
3. 新增本地持久化实现
4. 新增 replay builder
5. 让已有 `history_view` / `debug` 真正从持久化事件获益

一句话总结：

**v1.4 = 让事件从“当前进程里的调试材料”变成“可恢复、可回放、可继续工作的基础设施”。**

---

## 4. 新增/修改模块规划

### 4.1 新增文件

- `aicoder/events/backend.py`
- `aicoder/events/file_store.py`
- `aicoder/events/replay.py`
- `aicoder/events/serializer.py`
- `aicoder/tests/test_event_persistence.py`
- `aicoder/tests/test_event_replay.py`
- `aicoder/tests/test_session_resume.py`

### 4.2 重点修改文件

- `aicoder/events/store.py`
- `aicoder/events/types.py`
- `aicoder/agent_step_store.py`
- `aicoder/context/history_view.py`
- `aicoder/debug/dump_helpers.py`
- `aicoder/debug/context_trace.py`

### 4.3 可选少量修改文件

- `aicoder/graph/state.py`
- `aicoder/agent_runtime.py`
- `aicoder/agent_app_runner.py`

---

## 5. 分阶段实施

---

# 阶段 1：抽象 EventStore Backend 接口

## 5.1 目标
把当前内存事件仓抽象成统一 backend 接口，为持久化做准备。

## 5.2 要做的事

### 新建 `aicoder/events/backend.py`
定义统一接口，建议：

```python
from typing import Protocol
from aicoder.events.types import AgentEventRecord

class EventBackend(Protocol):
    def append(self, event: AgentEventRecord) -> None: ...
    def append_many(self, events: list[AgentEventRecord]) -> None: ...
    def all_events(self) -> list[AgentEventRecord]: ...
    def list_events(self, *, kind=None, iteration=None, limit=None) -> list[AgentEventRecord]: ...
    def last_event(self, kind=None) -> AgentEventRecord | None: ...
```

要求：
1. 先不要过度设计
2. 接口要能支撑内存 backend 和持久化 backend
3. `AgentEventStore` 对外 API 尽量保持不变

### 修改 `aicoder/events/store.py`
目标：
- `AgentEventStore` 组合 backend，而不是自己直接持有 `_events`

要求：
1. 默认仍使用内存 backend
2. 旧调用方式兼容

## 5.3 测试
新增到 `test_event_persistence.py`：
1. 默认 backend 为内存实现
2. AgentEventStore API 不变
3. append / list / last_event 仍正常

## 5.4 验收标准
1. EventStore backend 接口存在
2. 内存实现仍可工作
3. 测试通过

---

# 阶段 2：实现文件持久化事件仓

## 6.1 目标
给事件增加最小可用的本地持久化能力。

## 6.2 要做的事

### 新建 `aicoder/events/serializer.py`
提供：

- `event_to_dict(event: AgentEventRecord) -> dict`
- `event_from_dict(data: dict) -> AgentEventRecord`

要求：
1. 序列化必须稳定
2. created_at / iteration / kind / payload / event_id 都要保留

### 新建 `aicoder/events/file_store.py`
实现文件型 backend，建议格式：
- `jsonl`
或
- 单个 JSON 数组

优先建议：`jsonl`

提供：
- `append`
- `append_many`
- `load_all`
- `list_events`
- `last_event`

要求：
1. 每个 session 一个文件
2. 路径清晰，例如：
   - `.aicoder/events/<session_id>.jsonl`
3. 文件不存在时自动创建
4. 读失败不能把整个 agent 主链拖死，必须 graceful fallback

## 6.3 测试
新增 `test_event_persistence.py`：
1. append 后文件存在
2. 重新创建 store 后可读回
3. list_events/last_event 正常
4. payload 保真

## 6.4 验收标准
1. 持久化 backend 可用
2. 事件可跨实例读取
3. 测试通过

---

# 阶段 3：让 AgentStepStore 接入持久化事件仓

## 7.1 目标
让现有 step 生命周期事件自动写入可持久化 backend。

## 7.2 要做的事

### 修改 `aicoder/agent_step_store.py`
要求：
1. 构造时允许传入持久化型 `AgentEventStore`
2. 默认仍可用内存 store
3. 生命周期方法不需要大改 API，但实际写入 backend

### 建议新增构造辅助
如有必要，可加：
- `AgentEventStore.for_session(session_id, persist=True, root=...)`

要求：
1. 不要让业务调用方知道太多 backend 细节
2. session 到文件路径的映射要稳定

## 7.3 测试
新增：
1. AgentStepStore 用 file backend 时，生命周期事件真的落盘
2. 重建 store 后能看到旧事件
3. v1.2/v1.3 旧测试不回归

## 7.4 验收标准
1. step lifecycle 事件支持持久化
2. 主链不回归
3. 测试通过

---

# 阶段 4：实现 Replay Builder

## 8.1 目标
把持久化事件重新构造成可消费的历史视图。

## 8.2 要做的事

### 新建 `aicoder/events/replay.py`
实现：

- `replay_runtime_view(events: list[AgentEventRecord]) -> list[dict]`
- `replay_llm_view(events: list[AgentEventRecord], done_messages: list[dict], runner_type: str) -> list[dict]`
- 如有必要：
  - `replay_step_state(events: list[AgentEventRecord]) -> list[AgentStepLike]`

要求：
1. replay 不允许依赖当前进程的 step_store 内存对象
2. 必须从事件本身恢复足够多的信息
3. FC / CoT 都要兼容
4. condense 以后仍应作用在 replay 得到的 llm history view 上

## 8.3 修改 `aicoder/context/history_view.py`
要求：
1. 优先从 runner.step_store.event_store 获取事件
2. 当 step 对象缺失但事件存在时，允许走 replay 恢复
3. 不要破坏当前已有快路径

## 8.4 测试
新增 `test_event_replay.py`：
1. event -> runtime view replay 正常
2. event -> llm history view replay 正常
3. tool_error / tool_result replay 正常
4. FC / CoT replay 都能工作

## 8.5 验收标准
1. replay builder 存在且真实可用
2. history view 能利用 replay
3. 测试通过

---

# 阶段 5：实现 Session Resume 能力

## 9.1 目标
让 session 在重启后可恢复基本上下文和事件历史。

## 9.2 要做的事

### 修改 `aicoder/agent_runtime.py` 或 `aicoder/agent_app_runner.py`
要求：
1. session 启动时尝试加载对应 event file
2. 如果存在历史事件，则恢复 event store
3. 如果不存在，则正常新建

### 恢复的最小范围
至少恢复：
1. event store 内容
2. history view 输入来源
3. debug / dump 可见历史

可不在 v1.4 完整恢复的内容：
1. 当前未完成的半步 LLM 调用
2. 进程中断前正在执行的工具状态

### 要求
1. resume 失败不能阻塞 session 启动
2. 要有明确 fallback 到新 session/空事件仓的逻辑

## 9.3 测试
新增 `test_session_resume.py`：
1. 写入事件后重建 runtime，可看到事件
2. history view 恢复可用
3. debug helpers 恢复可用
4. 损坏事件文件时 graceful fallback

## 9.4 验收标准
1. session 基本 resume 能力存在
2. 持久化事件能被下一次进程启动利用
3. 测试通过

---

# 阶段 6：让 Debug / Dump 真正支持持久化事件

## 10.1 目标
让新的持久化事件能力可被诊断和检查。

## 10.2 要做的事

### 修改 `aicoder/debug/dump_helpers.py`
新增或增强：
- `dump_event_store(coder)`  
- `dump_replay_runtime_view(coder, mode, runner_type)`  
- `dump_replay_llm_view(coder, mode, runner_type)`

### 修改 `aicoder/debug/context_trace.py`
增加：
- 当前事件来源是内存 / 文件恢复
- replay 是否启用
- persisted event count

### 要求
1. debug 输出必须可测试
2. 不要把 raw payload 全量喷给最终用户
3. 保持开发者可诊断性

## 10.3 测试
补 `test_debug_modules.py` 或新增：
1. dump_event_store 可输出 persisted event count
2. replay debug 结果存在
3. resume 后 trace 仍可工作

## 10.4 验收标准
1. persistence / replay 可被 dump / trace
2. 测试通过

---

# 阶段 7：回归测试与稳定化

## 11.1 目标
确认 v1.4 没把 v1.3 的上下文系统搞坏。

## 11.2 要做的事

至少跑：
- `test_event_persistence.py`
- `test_event_replay.py`
- `test_session_resume.py`
- `test_debug_modules.py`
- `test_context_packer.py`
- `test_history_view.py`
- `test_condense.py`
- `test_regression_end_to_end.py`

必要时全量：

```bash
pytest aicoder/tests/ -x
```

## 11.3 验收标准
1. persistence / replay / resume 全链路可用
2. v1.3 核心上下文系统不回归
3. 测试通过

---

## 6. 具体文件修改清单

### 新增文件
- `aicoder/events/backend.py`
- `aicoder/events/file_store.py`
- `aicoder/events/replay.py`
- `aicoder/events/serializer.py`
- `aicoder/tests/test_event_persistence.py`
- `aicoder/tests/test_event_replay.py`
- `aicoder/tests/test_session_resume.py`

### 重点修改文件
- `aicoder/events/store.py`
- `aicoder/events/types.py`
- `aicoder/agent_step_store.py`
- `aicoder/context/history_view.py`
- `aicoder/debug/dump_helpers.py`
- `aicoder/debug/context_trace.py`

### 可选少量修改文件
- `aicoder/graph/state.py`
- `aicoder/agent_runtime.py`
- `aicoder/agent_app_runner.py`

---

## 7. 提交粒度要求

GLM 必须按以下粒度提交：

1. `feat: add event backend abstraction`
2. `feat: add file-backed event persistence`
3. `feat: persist step lifecycle events through file backend`
4. `feat: add event replay builders for runtime and llm views`
5. `feat: add session resume from persisted events`
6. `chore: extend debug and dump helpers for persisted event replay`

每一步都要：
- 修改代码
- 跑测试
- 输出变更说明
- 当前阶段通过后再进入下一阶段

---

## 8. 每阶段完成后的测试命令

优先运行：

```bash
pytest aicoder/tests/test_event_persistence.py
pytest aicoder/tests/test_event_replay.py
pytest aicoder/tests/test_session_resume.py
pytest aicoder/tests/test_debug_modules.py
pytest aicoder/tests/test_history_view.py
pytest aicoder/tests/test_condense.py
pytest aicoder/tests/test_regression_end_to_end.py
```

阶段性回归：

```bash
pytest aicoder/tests/ -x
```

最小回归集合：

```bash
pytest aicoder/tests/test_event_persistence.py aicoder/tests/test_event_replay.py aicoder/tests/test_session_resume.py aicoder/tests/test_context_packer.py
```

---

## 9. GLM 输出要求

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

## 10. 禁止性提醒

GLM 不允许做以下事情：

1. 不要重写 LangGraph 主链
2. 不要删除现有 AgentStepStore / AgentEventStore API
3. 不要把 replay 逻辑塞进 graph nodes
4. 不要把 persistence 做成“只有测试能用，主链没接”
5. 不要顺手重写 repo context / condensation
6. 不要引入大依赖
7. 不要只做内存恢复，忽略文件恢复
8. 不要把事件文件损坏情况忽略掉
9. 不要过度 mock 主路径
10. 不要把 debug 输出做成最终用户默认可见

---

## 11. 实施顺序总结

严格按这个顺序做：

1. Event backend 抽象
2. 文件持久化 backend
3. StepStore 接入持久化事件
4. Replay builder
5. Session resume
6. Debug / dump 增强
7. 回归测试与稳定化

不得跳序，除非当前阶段被代码现实阻塞，并在报告中明确说明原因。

---

## 12. 最终交付标准

完成后必须满足：

1. 事件可持久化
2. 事件可跨进程重新读取
3. 可基于事件 replay 出历史视图
4. session 可基本 resume
5. debug / dump 能看 persisted events 和 replay 结果
6. v1.3 的上下文系统不回归
7. 测试通过
