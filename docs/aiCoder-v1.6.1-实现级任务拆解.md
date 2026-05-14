# aiCoder v1.6.1 实现级任务拆解（稳定化与发布门禁）

更新时间：2026-05-13  
适用分支：`main`（建议 GLM 在 `codex/v1.6.1-hardening` 开发）  
目标类型：收尾修复 + 发布前门禁，不改架构主干

---

## 0. 背景与目标

v1.6 主能力（verification + recovery + checkpoint + replay）已打通。  
v1.6.1 目标不是扩功能，而是把“可发布性”做实：

1. **把恢复决策执行链做成可证伪**（有证据、有测试、有诊断）。  
2. **把检查点幂等做成可审计**（重复执行风险可追踪）。  
3. **把质量门禁固化进 CI**（不是人工口头验收）。

---

## 1. 范围边界（强约束）

### 1.1 允许修改

- `aicoder/graph/*`（仅 verify/recovery/route 相关）
- `aicoder/recovery/*`
- `aicoder/events/*`（仅新增事件字段或 replay 诊断）
- `aicoder/debug/*`
- `aicoder/tests/*`
- `.github/workflows/*`（若项目已有 CI）

### 1.2 禁止修改

- 不改三模式定义语义（sniff/plan/act）
- 不改 tool handler 对外接口（除非向后兼容）
- 不改 TUI/RPC 协议字段（除非新增可选字段）
- 不做大规模重构，不迁移目录结构

---

## 2. 验收标准（必须全部满足）

1. verify 后 recovery 的三类动作可被稳定重放：`retry/fallback/halt`。  
2. checkpoint guard 对“同一 step 同一 tool_call”重复执行有明确拦截证据。  
3. `context_trace` / `dump_helpers` 可直接看见 recovery 链路证据。  
4. 新增测试全部通过，且 v1.3-v1.6 关键回归无新增失败。  
5. 对已知 pre-existing failure（`test_sniffing_recon...`）不扩大影响。

---

## 3. 实施阶段

## 阶段 1：Recovery 决策执行证据化

### 目标
让 `verify_node -> route_after_verify -> observe/model/summarize` 的每次选择都有结构化证据。

### 实现任务
1. 在 recovery 决策写入处补全统一字段：
   - `action` (`retry|fallback|halt`)
   - `reason`
   - `next_hint`
   - `source_step_id`
   - `verification_task`
2. 在路由函数中写入可追踪字段到 state（如 `last_recovery_route`）。
3. 在事件流新增/补全 `recovery_routed` 事件（如已有则扩字段，保持兼容）。

### 测试要求
- 新增 `test_recovery_routing_trace.py`
  - 覆盖 retry/fallback/halt 三路
  - 覆盖“多 decision 并存时 halt 优先级”

### DoD
- 能从 event/replay 还原“为何进入该路由”。

---

## 阶段 2：Checkpoint 幂等审计闭环

### 目标
不仅“避免重复执行”，还要“看得见拦截发生过”。

### 实现任务
1. 在 guard 拦截分支写结构化事件：
   - `checkpoint_skip`
   - `session_id`, `step_id`, `tool_call_id`, `tool_name`
2. 在 replay 增加统计：
   - `skipped_duplicate_tool_calls`
3. 在恢复场景下补 1 个链路测试：首次执行成功 + 恢复后跳过重复调用。

### 测试要求
- 扩展 `test_checkpoint_recovery.py`
- 新增 `test_checkpoint_audit_trace.py`

### DoD
- dump/replay 中可见明确 skip 记录。

---

## 阶段 3：验证任务策略收敛（减少抖动）

### 目标
降低“无意义重复验证”与“失败后噪声重试”。

### 实现任务
1. 为 verification 结果引入轻量去抖规则：
   - 相同任务、相同输入、短窗口内失败可降频
2. 增加 `verification_suppressed` 事件（被降频时）
3. route 继续保持兼容，不改变现有主语义。

### 测试要求
- 扩展 `test_verification_policy.py`
- 扩展 `test_verification_runner.py`

### DoD
- 可观测 suppression 次数；无行为回归。

---

## 阶段 4：Debug/Dump 发布级可观测性

### 目标
调试输出可以直接用于发布验收单。

### 实现任务
1. `dump_quality_summary()` 增加：
   - recovery action 分布
   - checkpoint skip 次数
   - verification suppressed 次数
2. `trace_context()` 增加：
   - `verification.recent_tasks`
   - `recovery.last_action`
   - `checkpoint.last_skip`

### 测试要求
- 扩展 `test_debug_modules.py`
- 所有新增字段都有稳定断言

### DoD
- 一条 dump 输出可回答“系统是否健康”。

---

## 阶段 5：CI 门禁固化

### 目标
把口头验收变成自动门禁。

### 实现任务
1. 新增/更新 CI job（若已有 workflow 则补 job）：
   - `tests-core-v16x`：v1.6 主链关键集
   - `tests-regression-v13-v15`：历史关键回归集
2. 对 pre-existing failure 做显式注释处理（不隐藏真实失败）：
   - 允许单例已知失败，但必须写明原因与追踪 issue

### 测试要求
- 本地可执行同等命令并通过

### DoD
- PR 上能直接看见 gate 结果，非人工判断。

---

## 阶段 6：最终回归与交付清单

### 必跑命令（本地）

```powershell
python -m pytest aicoder/tests/test_checkpoint_recovery.py aicoder/tests/test_recovery_policy.py aicoder/tests/test_verification_policy.py aicoder/tests/test_verification_runner.py aicoder/tests/test_event_replay.py aicoder/tests/test_graph_workflow.py aicoder/tests/test_debug_modules.py -q
```

```powershell
python -m pytest aicoder/tests/ -q
```

### 交付模板（GLM 必须按此输出）
1. 修改文件清单（新增/修改分开）  
2. 每阶段完成状态（完成/未完成）  
3. 测试结果（通过数/失败数/预存失败）  
4. 风险与未闭环项  
5. 是否可合并（Yes/No + 理由）

---

## 4. 开发规范（给 GLM 的硬性执行规则）

1. 不允许跳阶段合并提交。  
2. 每阶段至少补 1 个失败用例后再修实现（先红后绿）。  
3. 所有新增事件必须结构化，禁止“仅文本描述”。  
4. 不得删除既有测试来“修绿”。  
5. 若遇到架构级阻塞，先停在当前阶段给阻塞报告，不得私自改范围。

---

## 5. 建议提交节奏

- Commit 1: phase1+tests  
- Commit 2: phase2+tests  
- Commit 3: phase3+phase4+tests  
- Commit 4: phase5(ci)+phase6(report)

---

## 6. 备注

- 本版本定位：`v1.6.1` 稳定化，不是 `v1.7` 功能扩展。  
- 若本版本稳定通过，再开启 `v1.7`（多会话协同/跨任务记忆/更强计划执行）规划。
