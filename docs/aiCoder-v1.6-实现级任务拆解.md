# aiCoder v1.6 实现级任务拆解
版本：v1.6  
主题：Verification & Recovery Hardening（验证闭环与恢复鲁棒性）  
目标读者：执行型编码 Agent（如 GLM）  
执行要求：强约束、按阶段提交、每阶段必须可运行、可测试、可回退

---

## 0. 本版目标

v1.6 只做 4 件事：

1. 建立“修改后自动验证”闭环（lint/test/check）并结构化回灌
2. 引入失败恢复策略（retry / fallback / halt）并纳入事件流
3. 强化 checkpoint 级恢复（进程中断后继续执行）的一致性
4. 提供可量化的质量评估与诊断输出（success rate / retry rate / verification latency）

---

## 1. 强约束

### 1.1 必须遵守
1. 不允许移除 LangGraph 主链
2. 不允许破坏 v1.5 已通过的 condensation / snapshot / retention 主链
3. 不允许破坏 v1.4 persistence / replay / resume
4. 验证闭环必须结构化记录到事件层，不允许只写日志文本
5. 验证失败策略必须由 policy 控制，不允许散落硬编码
6. 失败恢复流程必须可重放（replay 可见）
7. checkpoint 恢复不允许造成重复执行 destructive tool
8. 所有新能力都必须可 trace / dump / 测试
9. 每个阶段都必须补测试
10. deterministic fallback 必须保留，不允许把关键路径绑定在外部服务上

### 1.2 暂时禁止
1. 禁止重写 graph 核心节点拓扑
2. 禁止重写 tool registry / executor 主架构
3. 禁止大改 TUI / RPC 协议
4. 禁止做分布式任务调度
5. 禁止引入重型依赖（任务队列、外部数据库等）

### 1.3 代码风格要求
1. verification policy / execution policy / recovery policy 必须分模块
2. verification result 必须使用结构化模型（dataclass / TypedDict）
3. retry / fallback 决策必须可单测
4. 所有“自动重试”必须有最大上限和停止条件
5. 所有恢复逻辑必须幂等或有明确幂等保护

---

## 2. 完成定义

当 v1.6 完成时，系统必须满足：

1. 修改后可自动触发验证任务（按 mode + policy）
2. 验证结果可写入事件流并可在 history/debug 中检索
3. 工具/执行失败后可按策略进入 retry / fallback / halt
4. checkpoint 恢复后不会重复执行已完成的 tool step
5. replay 可以重建失败恢复轨迹
6. trace/dump 能展示验证状态、恢复路径、策略决策原因
7. v1.5 不回归
8. 测试通过

---

## 3. 总体设计方向

v1.6 不追求“更多能力”，而追求“更稳定交付”。  
一句话总结：

**v1.6 = 让 aiCoder 从“能做出修改”升级成“能自证修改质量，并在失败后可控恢复”。**

---

## 4. 新增/修改模块规划

### 4.1 新增文件

- `aicoder/verification/types.py`
- `aicoder/verification/policy.py`
- `aicoder/verification/runner.py`
- `aicoder/recovery/policy.py`
- `aicoder/recovery/engine.py`
- `aicoder/tests/test_verification_policy.py`
- `aicoder/tests/test_verification_runner.py`
- `aicoder/tests/test_recovery_policy.py`
- `aicoder/tests/test_checkpoint_recovery.py`
- `aicoder/tests/test_quality_metrics.py`

### 4.2 重点修改文件

- `aicoder/tools/result.py`
- `aicoder/agent_step_store.py`
- `aicoder/events/types.py`
- `aicoder/events/replay.py`
- `aicoder/context/history_view.py`
- `aicoder/graph/nodes.py`
- `aicoder/debug/dump_helpers.py`
- `aicoder/debug/context_trace.py`

### 4.3 可选少量修改

- `aicoder/agent_app_runner.py`
- `aicoder/runners/base_agent_runner.py`
- `aicoder/context/policies.py`

---

## 5. 分阶段实施

---

# 阶段 1：Verification 模型与策略定义

## 5.1 目标
定义“执行后验证”统一模型与模式策略。

## 5.2 要做的事

### 新建 `aicoder/verification/types.py`
建议定义：

```python
from dataclasses import dataclass, field
from typing import Literal

VerificationStatus = Literal["passed", "failed", "skipped", "error"]
VerificationLevel = Literal["light", "standard", "strict"]

@dataclass
class VerificationTask:
    task_id: str
    name: str
    command: str
    required: bool = True
    timeout_ms: int = 120000

@dataclass
class VerificationResult:
    task_id: str
    status: VerificationStatus
    exit_code: int | None = None
    duration_ms: int = 0
    output_preview: str = ""
```

### 新建 `aicoder/verification/policy.py`
按 mode 定义验证策略：
- `sniff`: 默认 `light`（通常跳过重验证）
- `plan`: 默认 `light`
- `act`: 默认 `standard`

并支持：
- `strict` 模式（如用户要求）
- 任务白名单/黑名单

## 5.3 测试
新增 `test_verification_policy.py`：
1. mode 到 verification level 映射正确
2. strict override 生效
3. task selection 可预测

## 5.4 验收标准
1. verification 数据结构存在
2. policy 存在且可测试
3. 测试通过

---

# 阶段 2：Verification Runner 接入主执行链

## 6.1 目标
让“修改后验证”真正可执行且可回灌。

## 6.2 要做的事

### 新建 `aicoder/verification/runner.py`
提供：
- `run_verification_tasks(coder, mode, changed_files, policy) -> list[VerificationResult]`

要求：
1. 支持多个任务顺序执行
2. 支持 timeout
3. 输出结构化结果
4. 失败不崩主链，交给 recovery policy 决策

### 修改 `aicoder/graph/nodes.py`
在合适节点（通常工具执行后 / summarize 前）接入 verification 调用。

要求：
1. 只在需要的模式触发
2. 触发条件可配置（例如有文件修改才触发）
3. 把 verification 结果放入 state（结构化）

## 6.3 测试
新增 `test_verification_runner.py`：
1. 成功任务结果正确
2. 失败任务结果正确
3. timeout 处理正确
4. 多任务聚合结果正确

## 6.4 验收标准
1. verification 能在主链真实触发
2. 结果结构化回灌
3. 测试通过

---

# 阶段 3：Recovery Policy 与决策引擎

## 7.1 目标
定义并实现失败后动作选择：retry / fallback / halt。

## 7.2 要做的事

### 新建 `aicoder/recovery/policy.py`
定义：
- 最大 retry 次数
- 可重试错误类型
- fallback 条件
- halt 条件

### 新建 `aicoder/recovery/engine.py`
提供：
- `decide_recovery_action(context) -> RecoveryDecision`

建议 `RecoveryDecision`：
- `action`: `retry` | `fallback` | `halt`
- `reason`
- `next_hint`

### 修改 `aicoder/graph/nodes.py`
把 verification failure / tool failure 接入 recovery engine。

要求：
1. 不允许无限重试
2. 错误要可解释
3. 决策结果进入 state 和事件流

## 7.3 测试
新增 `test_recovery_policy.py`：
1. 可重试错误 -> retry
2. 超过上限 -> halt
3. 非可重试错误 -> fallback 或 halt
4. 决策 reason/next_hint 存在

## 7.4 验收标准
1. recovery policy 生效
2. graph 主链可控恢复
3. 测试通过

---

# 阶段 4：事件模型扩展（Verification/Recovery Events）

## 8.1 目标
让验证与恢复成为可 replay 的一等事件。

## 8.2 要做的事

### 修改 `aicoder/events/types.py`
新增 event kinds：
- `verification_started`
- `verification_result`
- `verification_finished`
- `recovery_decision`
- `recovery_action_applied`

### 修改 `aicoder/agent_step_store.py` 或相关写事件路径
在 verification/recovery 关键点写事件。

### 修改 `aicoder/events/replay.py`
让 replay 视图可重建验证与恢复轨迹摘要。

## 8.3 测试
新增/修改：
- `test_event_replay.py`
- `test_verification_runner.py`

验证：
1. verification events 可回放
2. recovery events 可回放
3. UI/runtime view 能看到对应轨迹

## 8.4 验收标准
1. 新事件可持久化
2. 可 replay
3. 测试通过

---

# 阶段 5：Checkpoint 恢复一致性加固

## 9.1 目标
保证进程中断后恢复执行，不重复执行已完成 destructive tool。

## 9.2 要做的事

### 修改 runner / runtime 恢复逻辑
要求：
1. 恢复时识别最后已完成 step/tool
2. 幂等保护：
   - 已完成 tool_call_id 不重复执行
3. 保证恢复后可继续 verification/recovery 流程

### 建议实现
基于 persisted events 判断：
- `tool_call` + `tool_result` 完成对
- 若已完成则跳过执行，仅恢复观察结果

## 9.3 测试
新增 `test_checkpoint_recovery.py`：
1. 中断后恢复不重复执行已完成 tool
2. 恢复后可继续下一步
3. 恢复后 verification/recovery 路径正常

## 9.4 验收标准
1. checkpoint 恢复幂等
2. 无重复 destructive 执行
3. 测试通过

---

# 阶段 6：质量指标与调试观测

## 10.1 目标
提供可量化质量指标，支撑后续版本优化。

## 10.2 要做的事

### 修改 `aicoder/debug/dump_helpers.py`
新增：
- `dump_verification_metrics(coder)`
- `dump_recovery_metrics(coder)`
- `dump_quality_summary(coder)`

### 修改 `aicoder/debug/context_trace.py`
新增输出：
- verification task count / pass rate
- recovery action distribution
- retry count per session
- avg verification latency

### 指标建议
- `verification_pass_rate`
- `verification_fail_rate`
- `recovery_retry_rate`
- `halt_rate`
- `mean_verification_duration_ms`

## 10.3 测试
新增 `test_quality_metrics.py`：
1. 指标计算正确
2. 空数据不崩
3. 指标输出格式稳定

## 10.4 验收标准
1. 可输出质量指标
2. 指标可测试
3. 测试通过

---

# 阶段 7：回归测试与稳定化

## 11.1 目标
确认 v1.6 不破坏 v1.5/v1.4 核心链路。

## 11.2 要做的事

至少运行：
- `test_verification_policy.py`
- `test_verification_runner.py`
- `test_recovery_policy.py`
- `test_checkpoint_recovery.py`
- `test_quality_metrics.py`
- `test_resume_condensation.py`
- `test_snapshot_reuse.py`
- `test_tool_trace_policy.py`
- `test_event_persistence.py`
- `test_event_replay.py`
- `test_session_resume.py`
- `test_context_packer.py`
- `test_debug_modules.py`

必要时全量：

```bash
pytest aicoder/tests/ -x
```

## 11.3 验收标准
1. verification + recovery + checkpoint 三条链路可用
2. v1.5 不回归
3. v1.4 不回归
4. 测试通过

---

## 6. 具体文件修改清单

### 新增文件
- `aicoder/verification/types.py`
- `aicoder/verification/policy.py`
- `aicoder/verification/runner.py`
- `aicoder/recovery/policy.py`
- `aicoder/recovery/engine.py`
- `aicoder/tests/test_verification_policy.py`
- `aicoder/tests/test_verification_runner.py`
- `aicoder/tests/test_recovery_policy.py`
- `aicoder/tests/test_checkpoint_recovery.py`
- `aicoder/tests/test_quality_metrics.py`

### 重点修改文件
- `aicoder/tools/result.py`
- `aicoder/agent_step_store.py`
- `aicoder/events/types.py`
- `aicoder/events/replay.py`
- `aicoder/context/history_view.py`
- `aicoder/graph/nodes.py`
- `aicoder/debug/dump_helpers.py`
- `aicoder/debug/context_trace.py`

### 可选少量修改
- `aicoder/agent_app_runner.py`
- `aicoder/runners/base_agent_runner.py`
- `aicoder/context/policies.py`

---

## 7. 提交粒度要求

GLM 必须按以下粒度提交：

1. `feat: add verification models and mode policies`
2. `feat: add verification runner and integrate post-action checks`
3. `feat: add recovery policy and decision engine`
4. `feat: persist and replay verification/recovery events`
5. `feat: harden checkpoint recovery idempotency`
6. `chore: add quality metrics and debug observability`

每一步都要：
- 修改代码
- 跑测试
- 输出变更说明
- 当前阶段通过后再进入下一阶段

---

## 8. 每阶段完成后的测试命令

优先运行：

```bash
pytest aicoder/tests/test_verification_policy.py
pytest aicoder/tests/test_verification_runner.py
pytest aicoder/tests/test_recovery_policy.py
pytest aicoder/tests/test_checkpoint_recovery.py
pytest aicoder/tests/test_quality_metrics.py
pytest aicoder/tests/test_event_replay.py
pytest aicoder/tests/test_session_resume.py
pytest aicoder/tests/test_resume_condensation.py
pytest aicoder/tests/test_debug_modules.py
```

阶段性回归：

```bash
pytest aicoder/tests/ -x
```

最小回归集合：

```bash
pytest aicoder/tests/test_verification_runner.py aicoder/tests/test_recovery_policy.py aicoder/tests/test_checkpoint_recovery.py aicoder/tests/test_event_replay.py
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
2. 不要破坏 v1.5 snapshot/retention 主链
3. 不要让 verification 只存在于日志而不入事件流
4. 不要无限自动重试
5. 不要让 recovery 决策不可解释
6. 不要在恢复时重复执行已完成 destructive tool
7. 不要顺手大改 repo context
8. 不要引入大依赖
9. 不要只改测试不改主实现
10. 不要默认向最终用户暴露调试细节

---

## 11. 实施顺序总结

严格按这个顺序做：

1. Verification 模型与策略
2. Verification Runner 接入
3. Recovery Policy 与决策引擎
4. 事件模型扩展与 replay
5. Checkpoint 恢复一致性
6. 质量指标与调试观测
7. 回归测试与稳定化

不得跳序，除非当前阶段被代码现实阻塞，并在报告中明确说明原因。

---

## 12. 最终交付标准

完成后必须满足：

1. 验证闭环真实接入主链
2. 恢复策略可控可解释
3. checkpoint 恢复具备幂等保护
4. verification/recovery 事件可持久化并可 replay
5. 质量指标可观测可测试
6. v1.5 不回归
7. v1.4 不回归
8. 测试通过

