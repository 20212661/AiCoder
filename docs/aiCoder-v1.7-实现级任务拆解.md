# aiCoder v1.7 实现级任务拆解（Session Federation 跨会话连续性）

更新时间：2026-05-13  
适用分支：`main`（建议开发分支：`codex/v1.7-session-federation`）  
版本定位：在 v1.6.1 稳定基线上做“跨会话任务连续性”增强，不重写 v1.6 主链。

---

## 0. 目标定义

v1.7 的核心目标是：  
让 aiCoder 能在 **多个 session** 之间复用任务上下文与关键状态，实现“中断后可续、跨窗口可续、跨天可续”，并且保持可审计、可回放、可控预算。

---

## 1. 范围与约束

## 1.1 范围内

- 会话目录：`aicoder/session/*`（若无则新增）
- 事件/摘要复用：`aicoder/events/*`, `aicoder/context/*`
- 运行时接线：`aicoder/agent_app_runner.py`, `aicoder/graph/*`
- 调试与诊断：`aicoder/debug/*`
- 测试：`aicoder/tests/*`

## 1.2 明确不做

- 不改三模式（sniff/plan/act）语义
- 不改现有 tool handler 协议
- 不引入远程数据库或外部服务依赖
- 不做 UI 大改（仅增可选诊断字段）

---

## 2. 验收标准（必须全部满足）

1. 可创建“任务簇（task thread）”，一个任务可挂载多个 session。  
2. 新 session 启动时可从历史 session 自动恢复最小必要上下文（非全量灌入）。  
3. 历史恢复有预算上限，超限时自动压缩且可解释。  
4. 恢复链路全程有事件证据（federation_started/linked/restored/skipped）。  
5. debug/dump 能输出“本次恢复用了哪些 session、哪些摘要、丢了什么”。  
6. v1.6.1 核心回归不破坏（verification/recovery/checkpoint/replay）。

---

## 3. 阶段拆解

## 阶段 1：Session Federation 元数据层

### 目标
建立 session 之间的显式关系模型，不靠文件名或人工约定。

### 实现任务
1. 新增 `aicoder/session/federation.py`：
   - `TaskThread`
   - `SessionLink`
   - `FederationPolicy`
2. 新增本地持久化（jsonl/json）：
   - `.aicoder/session_federation/<task_thread_id>/*`
3. 提供 API：
   - `create_task_thread()`
   - `link_session(task_thread_id, session_id, role)`
   - `list_linked_sessions(task_thread_id)`

### 测试
- `test_session_federation_meta.py`

### DoD
- 可稳定创建/读取 task_thread 与 session 关系。

---

## 阶段 2：跨会话恢复输入构建器

### 目标
在新会话启动时，从关联 session 生成“恢复包”（restore bundle）。

### 实现任务
1. 新增 `aicoder/session/restore_bundle.py`：
   - 从 linked sessions 聚合：
     - 最近 summary snapshots
     - 关键 decisions
     - 未完成 next_steps
2. 恢复包结构化输出：
   - `goals`
   - `constraints`
   - `decisions`
   - `open_loops`
   - `critical_files`

### 测试
- `test_restore_bundle.py`

### DoD
- 恢复包可直接喂给 context packer，不依赖人工拼接文本。

---

## 阶段 3：预算控制与压缩接入

### 目标
恢复包不会挤爆上下文窗口，并能解释裁剪行为。

### 实现任务
1. 扩展 `aicoder/context/policies.py`：
   - 增加 federation 预算字段：
     - `federation_tokens`
     - `federation_sessions_cap`
2. 扩展 `aicoder/context/packer.py`：
   - 新层：`federation_context`
   - 按策略裁剪 linked sessions 数量与每 session 内容
3. 复用 v1.5 condensation 能力做二次压缩。

### 测试
- `test_federation_budget.py`

### DoD
- 超长历史下恢复包自动裁剪且 trace 可见裁剪原因。

---

## 阶段 4：运行时接线（主链最小侵入）

### 目标
把 federation 恢复流程接到主运行时，但不污染既有节点职责。

### 实现任务
1. `agent_app_runner.py` 在 `run_user_turn` 启动处增加：
   - `load_federation_restore_bundle(...)`
2. `graph/state.py` 增加可选字段：
   - `task_thread_id`
   - `federation_context`
   - `federation_trace`
3. `prepare_context` 节点接入 federation_context。

### 测试
- `test_graph_federation_flow.py`

### DoD
- 无 federation 配置时行为与 v1.6.1 完全一致。

---

## 阶段 5：事件与重放增强

### 目标
跨会话恢复必须可审计、可重放。

### 实现任务
1. 在 `events/types.py` 增加事件类型：
   - `federation_started`
   - `federation_session_linked`
   - `federation_restored`
   - `federation_skipped`
2. 扩展 replay：
   - `replay_federation_trace()`

### 测试
- `test_federation_replay.py`

### DoD
- 可复原“本轮用了哪些历史 session、为何跳过某些 session”。

---

## 阶段 6：可观测性与调试输出

### 目标
给验收者一眼看懂 federation 效果的诊断面板。

### 实现任务
1. `debug/context_trace.py` 增加：
   - federation layer tokens
   - selected sessions / skipped sessions
2. `debug/dump_helpers.py` 新增：
   - `dump_federation_context()`
   - `dump_federation_replay_trace()`

### 测试
- `test_federation_debug.py`

### DoD
- 一份 dump 可解释“恢复来源、预算占用、丢弃原因”。

---

## 阶段 7：回归门禁与发布准备

### 必跑测试

```powershell
python -m pytest aicoder/tests/test_graph_federation_flow.py aicoder/tests/test_federation_replay.py aicoder/tests/test_federation_budget.py aicoder/tests/test_federation_debug.py -q
```

```powershell
python -m pytest aicoder/tests/test_checkpoint_recovery.py aicoder/tests/test_recovery_policy.py aicoder/tests/test_verification_runner.py aicoder/tests/test_event_replay.py aicoder/tests/test_context_packer.py -q
```

```powershell
python -m pytest aicoder/tests/ -q
```

### DoD
- v1.7 新增测试通过；v1.6.1 核心链路无新增失败。

---

## 4. GLM 执行硬规则

1. 严格按阶段顺序执行，不得跳阶段。  
2. 每阶段先写失败测试，再写实现。  
3. 禁止删除既有测试以“修绿”。  
4. 所有新增行为必须有结构化事件证据。  
5. 若要超出范围改动，先提交阻塞报告并停工等待确认。

---

## 5. 阶段交付模板（每阶段都要输出）

1. 已完成事项  
2. 修改文件（新增/修改分开）  
3. 核心实现  
4. 测试清单与结果  
5. 风险与未闭环项  
6. 下一阶段计划

---

## 6. 合并门槛

- 通过标准：  
  - 新增 federation 相关测试全绿  
  - v1.6.1 核心回归无新增失败  
  - 至少 1 份真实 federation dump 示例可复核  
- 若仅通过单测但无可观测证据，不可合并。

