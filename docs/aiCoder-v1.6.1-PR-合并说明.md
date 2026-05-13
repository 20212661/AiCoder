# PR 标题

`v1.6.1: Recovery/Checkpoint 稳定化与发布门禁固化`

## 变更摘要

本次为 `v1.6.1` 稳定化收尾，不引入新架构，重点补齐 `verification -> recovery -> checkpoint -> replay/debug` 的发布级闭环。  
核心结果是：恢复决策可追踪、重复执行可审计、调试输出可验收、CI 门禁可自动化执行。

## 主要改动

1. Recovery 路由证据化  
`verify` 后路由决策补齐结构化字段（含来源 step/任务/原因/建议），并记录 `recovery_routed` 事件，可从事件流重建 `retry/fallback/halt` 决策路径。

2. Checkpoint 幂等审计闭环  
重复工具调用被 guard 拦截时，写入 `checkpoint_skip` 结构化事件；新增对应 dump/trace 指标，支持恢复场景下审计“跳过了什么、为什么跳过”。

3. Verification 去抖策略  
为短窗口重复验证失败场景增加 suppression 逻辑，并记录 `verification_suppressed` 事件，降低无效抖动与噪声重试。

4. Debug/Trace 可观测性增强  
`context_trace` 与 `dump_helpers` 增加 recovery/checkpoint/verification 维度输出，可直接用于发布验收。

5. CI 门禁固化  
新增（或扩展）`tests-core-v16x` 与 `tests-regression-v13-v15` 门禁任务，确保 v1.6 能力和 v1.3-v1.5 关键链路持续受保护。

## 测试结果

- 本地抽样复验（本次改动相关核心集）：`161 passed, 0 failed`。  
- 提供的全量回归：`1297 passed, 1 failed (pre-existing)`，失败为 `test_sniffing_recon.py::test_summary_empty_on_bad_root`，与本 PR 变更无关。  
- 无新增回归失败。

## 风险与兼容性

- 对主链行为是增强与可观测性补强，未改变三模式基础语义。  
- 新增事件字段保持向后兼容（增量字段/事件种类）。  
- 已知 pre-existing 失败未被放大。  
- 需在 push 后确认 CI 两条 gate 实际执行记录。

## 合并结论

建议合并（**Yes**）。  
当前版本已满足 `v1.6.1` 稳定化目标：可追踪、可审计、可回放、可门禁。

