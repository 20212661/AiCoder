# aiCoder v1.5 实现级任务拆解
版本：v1.5  
主题：Advanced Condensation / Long-Task Memory  
目标读者：执行型编码 Agent（如 GLM）  
执行要求：强约束、按阶段提交、每阶段必须可运行、可测试、可回退

---

## 0. 本版目标

v1.5 只做 4 件事：

1. 把当前模板式 condensation 升级成真正可演进的长任务 memory 系统
2. 让 persisted events 能生成可复用的 summary / snapshot，而不是每次从零压缩
3. 让 tool trace 保留策略更细粒度，避免“全留太贵、全删太傻”
4. 让 resume 后的长历史上下文继续可控、可解释、可调试

---

## 1. 强约束

### 1.1 必须遵守
1. 不允许移除 LangGraph 主链
2. 不允许破坏 v1.4 已通过的 Event Persistence / Replay / Resume
3. 不允许破坏 v1.3 已通过的 Repo Context / Focused File Budget / Context Trace
4. `ContextPacker` 仍必须是唯一上下文组装入口
5. 不允许把 condensation 重新做回“简单删消息”
6. 不允许让 summary 成为唯一真相，原始 persisted events 必须仍可保留
7. 所有 summary / snapshot 都必须可 trace / dump / 测试
8. resume 场景下必须优先复用已有 persisted summaries / snapshots
9. 每个阶段都必须补测试
10. 必须保留 deterministic fallback，不能把系统完全绑死在 LLM summarization 上

### 1.2 暂时禁止
1. 禁止重写 Event Store 为数据库系统
2. 禁止重写 graph nodes
3. 禁止大改 TUI / RPC
4. 禁止把 repo context 和 condensation 混成一个大模块
5. 禁止做复杂 subagent 编排
6. 禁止做跨机器同步

### 1.3 代码风格要求
1. policy / summarizer / snapshot / replay-consume 必须分模块
2. summary block 必须有结构化字段，不能只有一段自由文本
3. tool trace retention 规则必须可测试
4. 所有 debug 输出必须默认对最终用户不可见
5. 新增 dataclass / TypedDict 优先，避免再扩大裸 dict 传播范围

---

## 2. 完成定义

当 v1.5 完成时，系统必须满足：

1. 存在结构化 `SummaryBlock` / `CondensationSnapshot`
2. persisted events 可生成并复用 summary/snapshot
3. `build_llm_history_view()` 能优先消费 summary/snapshot，而不是每次从全量 event 现算
4. tool trace 保留策略至少区分：
   - recent critical traces
   - old summarized traces
   - removable bulky outputs
5. resume 后长 session 的上下文长度和压缩状态可控
6. debug / dump 能解释：
   - 哪些 event 被 summary 覆盖
   - 哪些 tool trace 被裁剪
   - 当前使用的是 fresh condensation 还是 persisted snapshot
7. v1.4 的 persistence / replay / resume 不回归
8. 测试通过

---

## 3. 总体设计方向

v1.5 不追求“更复杂的聊天历史”，而追求“更稳定的长任务记忆”。

本版重点借 OpenHands 的思想，但只吸收最有用的 4 个点：

1. **事件是基础真相**
2. **summary 是派生视图，不是覆盖原始历史**
3. **压缩结果要可持久化、可恢复**
4. **不同层消费不同形态的历史**

一句话总结：

**v1.5 = 让 aiCoder 从“会压缩历史”升级成“拥有可持续、可恢复、可解释的长任务记忆系统”。**

---

## 4. 新增/修改模块规划

### 4.1 新增文件

- `aicoder/context/summary_types.py`
- `aicoder/context/summary_store.py`
- `aicoder/context/snapshot.py`
- `aicoder/context/summarizer.py`
- `aicoder/context/tool_trace_policy.py`
- `aicoder/tests/test_summary_store.py`
- `aicoder/tests/test_snapshot_reuse.py`
- `aicoder/tests/test_tool_trace_policy.py`
- `aicoder/tests/test_resume_condensation.py`

### 4.2 重点修改文件

- `aicoder/context/condense.py`
- `aicoder/context/history_view.py`
- `aicoder/context/packer.py`
- `aicoder/context/policies.py`
- `aicoder/debug/dump_helpers.py`
- `aicoder/debug/context_trace.py`
- `aicoder/events/replay.py`

### 4.3 可选少量修改

- `aicoder/agent_app_runner.py`
- `aicoder/agent_step_store.py`
- `aicoder/graph/state.py`

---

## 5. 分阶段实施

---

# 阶段 1：定义 Summary / Snapshot 数据结构

## 5.1 目标
先把“压缩结果”从松散文本升级成结构化对象。

## 5.2 要做的事

### 新建 `aicoder/context/summary_types.py`
建议定义：

```python
from dataclasses import dataclass, field

@dataclass
class SummaryBlock:
    summary_id: str
    kind: str
    covered_event_ids: list[str]
    covered_iterations: list[int]
    goal: str = ""
    findings: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    raw_text: str = ""

@dataclass
class CondensationSnapshot:
    snapshot_id: str
    session_id: str
    source_event_count: int
    latest_event_id: str
    blocks: list[SummaryBlock] = field(default_factory=list)
```

要求：
1. `SummaryBlock` 必须可序列化
2. `covered_event_ids` 和 `covered_iterations` 必须明确
3. `raw_text` 可以保留，但不能是唯一表达

## 5.3 测试
新增 `test_summary_store.py` 最小结构测试：
1. `SummaryBlock` 可构造
2. `CondensationSnapshot` 可构造
3. 字段完整可断言

## 5.4 验收标准
1. summary/snapshot 有结构化数据模型
2. 后续阶段可依赖这些对象
3. 测试通过

---

# 阶段 2：实现 Summary Store

## 6.1 目标
让 condensation 结果可持久化，而不是只在当前调用里短暂存在。

## 6.2 要做的事

### 新建 `aicoder/context/summary_store.py`
建议提供：

- `save_snapshot(session_id, snapshot, root=...)`
- `load_latest_snapshot(session_id, root=...)`
- `list_snapshots(session_id, root=...)`

建议落盘位置：
- `.aicoder/summaries/<session_id>.json`
或
- `.aicoder/summaries/<session_id>/<snapshot_id>.json`

优先推荐第二种，便于保留历史版本。

### 要求
1. summary store 不能影响 event store 格式
2. 读取失败要 graceful fallback
3. snapshot 写入不能让主链崩溃

## 6.3 测试
新增 `test_summary_store.py`：
1. snapshot 可写入
2. snapshot 可重新读取
3. 多 snapshot 可列出
4. 损坏文件 graceful fallback

## 6.4 验收标准
1. summary snapshot 可持久化
2. 可跨进程读取
3. 测试通过

---

# 阶段 3：升级 Condensation Pipeline

## 7.1 目标
把 `condense.py` 从“单次生成摘要字符串”升级成“生成结构化 summary block + optional snapshot”。

## 7.2 要做的事

### 新建 `aicoder/context/summarizer.py`
提供两层能力：

1. deterministic summarizer
2. optional llm summarizer（后备增强）

建议接口：

- `summarize_events_deterministic(events, mode) -> SummaryBlock | None`
- `summarize_events_with_llm(events, coder, mode) -> SummaryBlock | None`
- `build_summary_block(events, mode, coder=None) -> SummaryBlock | None`

### 修改 `aicoder/context/condense.py`
要求：
1. `prune_history_events()` 保留
2. 原有 `summarize_history_events()` 升级为返回 `SummaryBlock`
3. 新增 snapshot 构建函数，例如：
   - `build_condensation_snapshot(events, mode, coder=None) -> CondensationSnapshot | None`
4. 原 `apply_condensation_to_history_view()` 改为消费 `SummaryBlock`

### 要求
1. deterministic summarizer 必须一直可用
2. LLM summarizer 只能是增强层，不能是唯一依赖
3. SummaryBlock 的 `goal / findings / failures / next_steps / files_touched` 必须真实填充

## 7.3 测试
新增 `test_resume_condensation.py` / 修改 `test_condense.py`：
1. 新 summary block 结构可生成
2. deterministic 路径无 LLM 也可工作
3. apply_condensation 可消费 `SummaryBlock`
4. 原有 condense 行为不回归

## 7.4 验收标准
1. Condensation Pipeline 升级成功
2. SummaryBlock 成为正式中间产物
3. 测试通过

---

# 阶段 4：引入 Tool Trace Retention Policy

## 8.1 目标
让旧 tool trace 的保留不再只是粗暴按字符裁剪，而是有策略地保留重要信息。

## 8.2 要做的事

### 新建 `aicoder/context/tool_trace_policy.py`
建议提供：

- `class ToolTraceRetentionDecision`
- `class ToolTracePolicy`
- `decide_tool_trace_retention(events, mode, budget_tokens) -> ...`

### 初版策略至少区分：

1. **must_keep**
   - 最近几轮 tool call/result
   - 错误事件
   - permission denied
   - 关键文件操作

2. **summarize_only**
   - 旧但仍有价值的 tool_result
   - 长读取输出
   - 长 list/search 输出

3. **trim_aggressively**
   - 陈旧且重复的工具输出

### 修改 `aicoder/context/condense.py`
要求：
1. prune 逻辑接入 tool trace retention policy
2. 旧工具输出的裁剪不只按“older half”
3. 要能够在 summary 中保留被裁剪工具的摘要

## 8.3 测试
新增 `test_tool_trace_policy.py`：
1. recent tool traces 比 old traces 更易保留
2. errors 不会被过度裁剪
3. repeated bulky outputs 会被 aggressive trim
4. summarized traces 仍在 summary 中有痕迹

## 8.4 验收标准
1. tool trace retention 有独立策略
2. 策略真实接入 condensation
3. 测试通过

---

# 阶段 5：让 Resume 优先复用 Snapshot

## 9.1 目标
让 resume 后不必每次都从全量 persisted events 重新算 summary。

## 9.2 要做的事

### 修改 `aicoder/context/history_view.py`
在 `build_llm_history_view()` 路径中补：
1. 先查 persisted snapshot
2. 如果 snapshot 覆盖到最新 event 或足够接近，则优先复用
3. 再把 snapshot 之后的新 events 增量补上

建议策略：
- snapshot + recent unsummarized events

### 新建 `aicoder/context/snapshot.py`
可提供：

- `snapshot_covers_events(snapshot, events) -> bool`
- `merge_snapshot_with_recent_events(snapshot, events, runner_type, done_messages) -> list[dict]`

### 要求
1. snapshot 只是优化和稳定化，不是唯一来源
2. snapshot 不可用时必须回退到 fresh replay + condense
3. resume 路径必须可测试

## 9.3 测试
新增 `test_snapshot_reuse.py` / `test_resume_condensation.py`：
1. 已有 snapshot 时优先复用
2. snapshot 过期时回退 fresh condensation
3. resume 后 llm history view 可见 snapshot + recent events
4. FC / CoT 都能工作

## 9.4 验收标准
1. resume 已支持 snapshot reuse
2. llm history 构造更稳定
3. 测试通过

---

# 阶段 6：把 Snapshot / Summary 接入 Debug / Dump / Trace

## 10.1 目标
让长任务 memory 变得可解释。

## 10.2 要做的事

### 修改 `aicoder/debug/dump_helpers.py`
新增或增强：

- `dump_summary_blocks(coder, mode)`
- `dump_snapshot_state(coder, mode)`
- `dump_tool_trace_retention(coder, mode)`

### 修改 `aicoder/debug/context_trace.py`
新增输出：
- 当前是否使用 snapshot
- snapshot 覆盖 event 数
- recent unsummarized event 数
- tool trace retention 统计
- summary block 数量

### 要求
1. trace/dump 必须可测试
2. 不默认暴露给最终用户
3. 结构化输出优先于长字符串

## 10.3 测试
新增 `test_resume_condensation.py` / 修改 `test_debug_modules.py`：
1. dump_summary_blocks 有输出
2. dump_snapshot_state 能区分 reused / rebuilt
3. trace_context 可报告 snapshot / tool trace retention 状态

## 10.4 验收标准
1. snapshot / summary / retention 可被诊断
2. debug 输出可测试
3. 测试通过

---

# 阶段 7：回归测试与稳定化

## 11.1 目标
确保 v1.5 没把 v1.4 的 persistence/replay 和 v1.3 的 context 系统搞坏。

## 11.2 要做的事

至少运行：

- `test_summary_store.py`
- `test_snapshot_reuse.py`
- `test_tool_trace_policy.py`
- `test_resume_condensation.py`
- `test_event_persistence.py`
- `test_event_replay.py`
- `test_session_resume.py`
- `test_context_packer.py`
- `test_history_view.py`
- `test_condense.py`
- `test_debug_modules.py`
- `test_regression_end_to_end.py`

必要时全量：

```bash
pytest aicoder/tests/ -x
```

## 11.3 验收标准
1. summary/snapshot/tool-trace-retention 全链路可用
2. v1.4 persistence / replay / resume 不回归
3. v1.3 context system 不回归
4. 测试通过

---

## 6. 具体文件修改清单

### 新增文件
- `aicoder/context/summary_types.py`
- `aicoder/context/summary_store.py`
- `aicoder/context/snapshot.py`
- `aicoder/context/summarizer.py`
- `aicoder/context/tool_trace_policy.py`
- `aicoder/tests/test_summary_store.py`
- `aicoder/tests/test_snapshot_reuse.py`
- `aicoder/tests/test_tool_trace_policy.py`
- `aicoder/tests/test_resume_condensation.py`

### 重点修改文件
- `aicoder/context/condense.py`
- `aicoder/context/history_view.py`
- `aicoder/context/packer.py`
- `aicoder/context/policies.py`
- `aicoder/debug/dump_helpers.py`
- `aicoder/debug/context_trace.py`
- `aicoder/events/replay.py`

### 可选少量修改
- `aicoder/agent_app_runner.py`
- `aicoder/agent_step_store.py`
- `aicoder/graph/state.py`

---

## 7. 提交粒度要求

GLM 必须按以下粒度提交：

1. `feat: add structured summary and snapshot types`
2. `feat: add persistent summary store`
3. `feat: upgrade condensation pipeline to structured summary blocks`
4. `feat: add tool trace retention policy`
5. `feat: reuse snapshots during resume history rebuild`
6. `chore: extend debug and trace for summary and snapshot state`

每一步都要：
- 修改代码
- 跑测试
- 输出变更说明
- 当前阶段通过后再进入下一阶段

---

## 8. 每阶段完成后的测试命令

优先运行：

```bash
pytest aicoder/tests/test_summary_store.py
pytest aicoder/tests/test_snapshot_reuse.py
pytest aicoder/tests/test_tool_trace_policy.py
pytest aicoder/tests/test_resume_condensation.py
pytest aicoder/tests/test_event_persistence.py
pytest aicoder/tests/test_event_replay.py
pytest aicoder/tests/test_session_resume.py
pytest aicoder/tests/test_debug_modules.py
pytest aicoder/tests/test_condense.py
```

阶段性回归：

```bash
pytest aicoder/tests/ -x
```

最小回归集合：

```bash
pytest aicoder/tests/test_resume_condensation.py aicoder/tests/test_session_resume.py aicoder/tests/test_condense.py aicoder/tests/test_debug_modules.py
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
2. 不要删除 v1.4 的 persistence / replay / resume 能力
3. 不要把 summary/snapshot 做成只有测试能用、主链不用
4. 不要让 LLM summarizer 成为唯一必需路径
5. 不要把 tool trace retention 写死在一个大 if/else 函数里且不可测试
6. 不要顺手重写 repo context
7. 不要把 debug 输出做成默认用户可见
8. 不要引入大依赖
9. 不要过度 mock 主逻辑
10. 不要为了通过测试把原始 persisted events 删除或覆盖

---

## 11. 实施顺序总结

严格按这个顺序做：

1. Summary / Snapshot 数据结构
2. Summary Store
3. Condensation Pipeline 升级
4. Tool Trace Retention Policy
5. Resume 优先复用 Snapshot
6. Debug / Dump / Trace 增强
7. 回归测试与稳定化

不得跳序，除非当前阶段被代码现实阻塞，并在报告中明确说明原因。

---

## 12. 最终交付标准

完成后必须满足：

1. condensation 产物结构化
2. summary/snapshot 可持久化并可恢复
3. resume 后 llm history view 可优先复用 snapshot
4. tool trace retention 有独立策略且真实生效
5. debug / dump / trace 能解释 summary / snapshot / retention 状态
6. v1.4 persistence / replay / resume 不回归
7. v1.3 context system 不回归
8. 测试通过
