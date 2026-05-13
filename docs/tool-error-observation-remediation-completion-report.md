# 工具失败 Observation 改造完成报告

生成时间: 2026-05-12

## 一句话说明

AiCoder 已完成“FC 参数归一化 + 工具失败 observation 契约 + Step Store 双写一致化”三项最小改造，工具失败现在能够稳定回灌模型、进入历史重建，并保持与运行时消息链路一致。

## 背景

本次改造对应以下收敛目标：

- 修复 Function Calling 路径下非 `dict` 工具参数被直接清空为 `{}`` 的问题
- 固化“工具失败属于 observation，不属于 agent-level fatal error”的运行契约
- 打通运行时 observation 与 step store / history rebuild 之间的一致性

本次工作基于既有设计文档推进：

- [aicoder-tool-error-observation-minimal-remediation.md](/D:/CodingProject/aiCoder/docs/aicoder-tool-error-observation-minimal-remediation.md)

## 完成项

### Phase A: FC 参数归一化

- `function_calling_agent_runner.py` 新增 `_normalize_tool_params()`，完成 FC 参数进入执行器前的统一归一化
- 支持单参数工具的字符串自动包装
- 支持 JSON 字符串参数解析为 `dict`
- 对不可归一化参数，生成明确 observation，而不是降级为 `{}` 或伪造成功调用
- `base_agent_runner.py` 的 `StepResult` 新增 `failed_observations` 字段，用于承接 runner 级参数归一化失败结果
- `graph/nodes.py` 的 `_model_node_via_runner()` 增加对归一化失败 observation 的处理，并写入 `tool_observations`

本阶段完成后，FC 路径不再存在“参数可恢复但被框架主动丢失”的问题。

### Phase B: 工具失败 observation 契约

- `tools/executor.py` 的 `execute()` 增加 defensive `try/except` 收口，确保工具层故障不会把异常直接抛穿主链
- `tools/result.py` 的工厂方法统一补齐 `meta` 字段，至少包含：
  - `success`
  - `rejected`
  - `tool_name`
- 工具成功、失败、拒绝三类结果现在都有稳定的结构化元信息
- 工具失败继续沿用 observation 链路，而不是升级为整轮 Agent 中断

本阶段完成后，AiCoder 的工具执行层正式具备稳定的“失败收敛为 observation”语义，不再依赖局部实现细节。

### Phase C: Step Store 双写一致化

- `graph/nodes.py` 的 `execute_tool_node()` 在工具执行后，同步把结果写入 step store
- step 回写内容包含 observation 与 `tool_meta`
- `agent_history_rebuilder.py` 的 `build_for_cot()` 和 `build_for_fc()` 均改为根据 `tool_meta.success` / `tool_meta.rejected` 区分：
  - 成功
  - 失败
  - 拒绝

本阶段完成后，运行时消息链路与历史重建链路使用的是同一份工具结果语义，不再出现“模型看到了失败，但 step 历史里没有正确落账”的分叉。

## 关键结果

本次改造最终达成了以下结果：

1. FC 路径不再把非 `dict` 参数默认清空为 `{}`。
2. 单参数工具可以自动包装纯字符串参数。
3. 多参数工具遇到不可归一化参数时，能够生成明确 observation。
4. 工具失败不会中断正常 Agent 循环。
5. 失败结果能够进入下一轮 prompt，供模型自纠错使用。
6. step store 能记录工具成功、失败、拒绝三类 observation。
7. history rebuild 能正确还原成功、失败、拒绝三类工具消息。

## 测试覆盖

本次改造测试覆盖如下：

- 新增 `test_fc_param_normalization.py`，10 个测试
- 新增 `test_tool_executor.py`，17 个测试
- 新增 `test_graph_observation.py`，7 个测试
- 更新 `test_agent_history_rebuilder.py`，新增 7 个测试

全量测试结果：

- `560 tests passed`
- 零回归

## 影响范围

本次改造的主要影响模块如下：

| 文件 | 改动说明 |
|------|------|
| `aicoder/runners/function_calling_agent_runner.py` | 增加 FC 参数归一化与归一化失败 observation 逻辑 |
| `aicoder/runners/base_agent_runner.py` | `StepResult` 增加 `failed_observations` 字段 |
| `aicoder/graph/nodes.py` | runner 失败 observation 接入、工具结果双写回 step store |
| `aicoder/tools/executor.py` | defensive 异常收口，确保工具失败不抛穿主链 |
| `aicoder/tools/result.py` | 工厂方法统一补齐 `meta` 语义字段 |
| `aicoder/agent_history_rebuilder.py` | 基于 `tool_meta` 重建成功/失败/拒绝三类历史 |

## 与设计目标的对齐情况

### 已完成

- 已完成 FC 参数归一化最小闭环
- 已完成工具失败 observation 契约固定
- 已完成 step store 与运行时 observation 双写一致化
- 已完成 history rebuild 对失败/拒绝语义的识别
- 已完成针对核心回归面的测试补强

### 未扩展项

以下内容未纳入本次最小改造范围，且本次没有扩张实现边界：

- 未引入新的 `ToolEngine`
- 未重写 LangGraph 工作流
- 未引入新的数据库持久化层
- 未重构 ToolRegistry 全部 schema 建模
- 未扩展为附件/二进制/流式 tool message 协议

## 当前收益

本次改造带来的直接收益包括：

- 模型在 FC 模式下的工具调用容错更强
- 工具失败后模型自纠错能力更稳定
- 工具执行失败的排查路径更清晰
- step 历史、消息历史、运行时 observation 三者语义一致
- 后续做会话恢复、历史压缩、执行可视化时基础更稳

## 当前已知边界

虽然本次改造已经完成最小闭环，但仍有以下边界需要明确：

1. 单参数自动包装依赖当前工具参数元信息质量；若后续新增工具但参数描述不完整，仍可能影响归一化效果。
2. `tool_meta` 当前以最小字段集为主，足够支撑成功/失败/拒绝判定，但还不是完整执行审计模型。
3. 本次重点覆盖了工具执行语义一致性，没有扩展到更复杂的多阶段工具事务场景。

## 结论

本次“工具失败 observation”改造已经完成预定最小目标，且形成了可验证、可重建、可持续扩展的收敛结果。

从当前状态看，这项工作已经不是局部补丁，而是把 AiCoder 在工具调用失败场景下的运行语义正式拉齐到了统一标准：

- 参数尽量归一化
- 工具失败进入 observation
- observation 进入下一轮模型
- 结果进入 step store
- history rebuild 还原真实语义

这意味着后续无论是继续增强 FC 支持、做执行可观测性建设，还是做更稳的会话恢复，都已经建立在一条一致的工具结果主链上。
