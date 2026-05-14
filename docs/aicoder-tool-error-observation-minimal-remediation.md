# AiCoder 工具失败观测链路最小改造清单

## 1. 文档目标

本文档用于把 Dify 中“工具参数归一化 + 工具失败不打断 Agent + 失败结果回灌模型”的设计，收敛为一份适用于 AiCoder 当前架构的最小改造清单。

本文档是强约束实施文档，不是讨论稿。凡标记为“必须”的项，实施时不得省略、替换或弱化；凡标记为“禁止”的项，实施时不得引入。

---

## 2. 改造范围

本次改造只允许落在以下范围内：

- `aicoder/parsers/function_call_parser.py`
- `aicoder/runners/function_calling_agent_runner.py`
- `aicoder/tools/executor.py`
- `aicoder/tools/result.py`
- `aicoder/graph/nodes.py`
- `aicoder/runners/base_agent_runner.py`
- `aicoder/agent_step_store.py`
- `aicoder/agent_history_rebuilder.py`
- 与上述逻辑直接对应的测试文件

本次改造禁止扩散到以下范围：

- 不重写 `LangGraph` 工作流
- 不重构 `ToolRegistry` 整体模型
- 不新增数据库存储层
- 不修改模式权限语义 `sniff / plan / act`
- 不改动前端 UI 协议
- 不引入新的“全局异常吞掉器”覆盖 LLM 调用层

---

## 3. 总体目标

本次改造完成后，AiCoder 必须满足以下三个目标：

1. Function Calling 路径下，工具参数在进入执行器前必须完成统一归一化，不能把“可恢复参数”直接降级为 `{}`。
2. 工具层失败必须以结构化失败结果返回，不能因为工具错误中断整个 Agent 回合。
3. 工具执行结果必须同时写入：
   - 下一轮 prompt 可见的 observation 消息
   - step store 中的 observation / error 状态
   这两条链路必须保持一致。

---

## 4. 改造原则

### 4.1 必须遵守

- 必须保持当前 `ToolExecutor -> ToolResult -> observation` 主链路不变。
- 必须优先做“最小补洞”，不能借机引入第二套工具执行框架。
- 必须让 CoT runner 与 FC runner 在“工具成功/失败后的语义”上尽量一致。
- 必须让历史重建依赖 step store 时，得到的结果与运行时 observation 语义一致。
- 必须优先保留现有测试语义，新增测试覆盖缺口，不得用删除测试换取通过。

### 4.2 明确禁止

- 禁止把工具失败重新改回直接抛异常到 graph 顶层。
- 禁止在 FC runner 中继续使用“非 dict 参数直接置空 `{}`”的策略。
- 禁止只更新 `cur_messages` 而不更新 step store。
- 禁止只更新 step store 而不更新 `messages` / `tool_observations`。
- 禁止在参数归一化失败时静默吞掉错误并伪装成成功调用。

---

## 5. 最小改造项

## 5.1 改造项 A：FC 工具参数归一化

### 目标

把 `FunctionCallParser` 和 `FunctionCallingAgentRunner` 之间的参数交接从“尽量解析，失败就丢成空 dict”改成“尽量归一化，归一化失败则保留失败语义并进入现有错误 observation 链路”。

### 当前问题

当前 FC 路径存在以下问题：

- `function.arguments` 如果是合法 JSON object，可以正常得到 `dict`
- 如果是字符串形式的单参数值，例如 `"北京"`，当前 runner 会直接变成 `{}``
- 如果是 JSON 字符串但解析失败，当前 runner 也会直接变成 `{}`

这会导致模型本来给了“部分可恢复参数”，系统却把它主动丢失，最终只剩一个笼统的“缺少参数”失败。

### 必须实现

必须新增一个统一参数归一化步骤，建议放在 FC runner 内部，或抽成一个小型 helper，但不得引入新的大型基础设施。

归一化规则必须严格如下：

1. 若 `action_input` 已经是 `dict`：
   - 直接使用
2. 若 `action_input` 是 `str`：
   - 先读取目标工具的参数 schema 或 required params 信息
   - 若该工具只有一个 LLM-facing 必填参数，必须自动包装为 `{唯一参数名: 原字符串}`
   - 否则必须尝试 `json.loads(action_input)`
   - 若解析结果是 `dict`，使用该 dict
   - 若仍不是 `dict`，必须保留“参数归一化失败”语义，不能退化成 `{}`
3. 若 `action_input` 是其他类型：
   - 必须尝试安全转为 `dict`
   - 转换失败时进入“参数归一化失败”

### 必须产出的失败语义

当参数归一化失败时，必须满足以下约束：

- 不能创建一个伪造的空参数工具调用
- 不能直接让本轮 Agent 崩溃
- 必须产生一条明确 observation，语义等价于：
  `Invalid params: tool arguments could not be normalized to a dict`
- 必须把这条失败继续喂回下一轮模型

### 建议实现位置

- 首选：`aicoder/runners/function_calling_agent_runner.py`
- 可选：`aicoder/parsers/function_call_parser.py` 只负责保留 raw，不承担工具 schema 感知

### 实施约束

- `FunctionCallParser` 禁止依赖 `ToolRegistry`
- 工具参数名推断逻辑必须只依赖 AiCoder 现有工具定义
- 若当前工具元数据不足以判断“单参数工具”，必须显式记录这一限制，不得猜测

### 完成标准

以下输入必须表现正确：

| 场景 | 输入 arguments | 工具参数结构 | 期望 |
|---|---|---|---|
| 单参数字符串 | `"北京"` | 单参数 `city` | 自动包装成 `{"city":"北京"}` |
| 多参数 JSON 字符串 | `"{\"city\":\"北京\"}"` | 多参数 | 解析成 dict |
| 多参数普通字符串 | `"北京"` | 多参数 | 参数归一化失败，生成 observation |
| 非法 JSON 字符串 | `"{bad json}"` | 多参数 | 参数归一化失败，生成 observation |

---

## 5.2 改造项 B：工具失败统一走 observation，不中断 Agent

### 目标

把 AiCoder 当前已经具备但尚未完全制度化的行为，收敛为明确契约：

- 工具错误属于 observation
- 不是 agent-level fatal error

### 当前状态

当前 `ToolExecutor.execute()` 已经具备较好的失败收敛能力：

- 未知工具返回 `ToolResult.fail`
- 参数校验失败返回 `ToolResult.fail`
- 权限拒绝返回 `ToolResult.blocked`
- 用户拒绝返回 `ToolResult.create_rejected`
- 执行异常 / 超时经过 `_execute_with_retry()` 收敛成 `ToolResult.fail`

这条主链是正确的，本次不是推翻，而是补强契约边界。

### 必须实现

必须明确以下规则，并以代码与测试固定下来：

1. 工具层允许失败，但失败必须返回 `ToolResult`
2. `ToolExecutor.execute()` 对 handler 执行期异常必须继续收敛为失败结果
3. graph 执行层必须把所有失败结果都写入 `tool_observations`
4. `observe_tool_result()` 必须把失败结果转换为下一轮模型可见的消息
5. 除非是 LLM 调用失败、graph 自身损坏、进程级错误，否则工具失败不得中止整轮 Agent

### 必须统一的失败文本规范

失败文本必须尽量稳定，避免测试和 prompt 漂移。建议统一为以下前缀：

- 未知工具：`Unknown tool: <tool_name>`
- 参数错误：`Invalid params: <detail>`
- 执行错误：`Execution error: <detail>`
- 超时错误：`Tool timed out after <n>s. Try breaking the operation into smaller steps.`
- 权限拒绝：沿用现有拒绝 reason
- 用户拒绝：`User rejected the tool call.`

### 明确禁止

- 禁止有的失败写 `output`，有的失败只写 `error`，但最终 observation 文本不一致
- 禁止在 graph 某个分支里丢掉失败 observation
- 禁止把“参数归一化失败”作为 runner 内部静默过滤

### 完成标准

以下情况都必须继续进入下一轮模型，而不是直接中断：

- 工具名不存在
- 参数缺失
- 参数格式不合法
- 工具执行抛异常
- 工具超时
- 权限拒绝
- 用户审批拒绝

---

## 5.3 改造项 C：step store 与 observation 双写一致化

### 目标

确保“运行时消息链路”和“step 持久化链路”表达的是同一件事，避免当前只写消息、不写 step 的割裂状态。

### 当前问题

当前 runner 层虽然提供了：

- `_update_step_after_tool()`
- `_mark_step_error()`

但主执行路径主要仍在 `graph/nodes.py` 中通过：

- `tool_observations`
- `coder.cur_messages.append(result.to_message())`

来推进下一轮上下文。

这会导致：

- 模型能看到 observation
- 但 step store 未必完整记录 observation / error
- `AgentHistoryRebuilder` 在依赖 step 重建历史时，可能拿不到真实工具结果

### 必须实现

必须新增一条“工具执行结果回写 step”的路径，并满足以下约束：

1. 只要某个 step 已经产生了 `action_name`
2. 且该 step 对应工具已经返回 `ToolResult`
3. 就必须把结果同步回该 step

回写规则必须严格如下：

- `result.success == True`
  - 调用 `_update_step_after_tool(...)`
  - `observation = result.output`
  - `tool_meta = result.meta`
- `result.success == False and result.rejected == False`
  - 推荐仍使用 `_update_step_after_tool(...)`
  - `observation = result.error or result.output`
  - 不建议标成 `error` 状态，除非你要把 runner 级异常与工具失败语义区分开
- `result.rejected == True`
  - 仍必须回写 observation
  - observation 文本必须与用户可见文本一致

### 强约束决策

本次改造建议采用以下单一语义，禁止左右摇摆：

- “工具调用到了执行器并返回结果”，无论成功失败拒绝，一律记为 `observed`
- “runner/LLM/框架级错误导致本轮根本没有有效 tool result”，才记为 `error`

也就是说：

- `step.status = observed` 表示“工具结果已产生”
- `step.observation` 承载成功或失败文本
- `step.error` 只保留给框架级故障

这是本次文档的推荐强约束，实施时应优先遵守。

### 为什么要这么定

因为当前系统的主设计是“工具失败也是 observation”，不是“工具失败等于框架异常”。

如果把工具失败大量写进 `step.error`：

- 会导致 history rebuild 语义分叉
- 会让 FC/CoT 两条 runner 对失败的表达不一致
- 会削弱“模型根据失败 observation 自纠错”的主目标

### 必须修改的消费端

如果采用上述单一语义，则以下逻辑必须同步检查：

- `AgentHistoryRebuilder.build_for_cot()`
- `AgentHistoryRebuilder.build_for_fc()`
- 任何读取 `step.status == "error"` 来构造工具失败历史的地方

必须保证：

- 工具失败如果已写入 `observed`
- history rebuild 仍然能把它还原为失败 observation，而不是误当成功

### 推荐实现方式

给 `AgentStep.tool_meta` 增加最小失败语义字段，至少包含：

- `success: bool`
- `rejected: bool`
- `tool_name: str`

必要时可再加：

- `error: str`

这样 history rebuild 不必再靠 `status` 猜测成功失败。

### 完成标准

以下断言必须成立：

1. 工具成功后，step 中有 observation，history rebuild 能重建成功结果
2. 工具失败后，step 中仍有 observation，history rebuild 能重建失败结果
3. 用户拒绝后，step 中仍有 observation，history rebuild 能重建拒绝结果
4. 只有 runner/LLM/系统级异常才进入 `step.status == "error"`

---

## 6. 建议实施顺序

必须按以下顺序实施，禁止乱序混改：

1. 先补 FC 参数归一化
2. 再固定工具失败 observation 契约
3. 最后补 step store 双写与 history rebuild

原因如下：

- 若先改 step store，而参数仍持续被清空为 `{}`，你只是在持久化错误行为
- 若先改 history rebuild，而 runtime observation 契约还不稳定，会引入更多分叉

---

## 7. 具体改造清单

## 7.1 文件级任务

### `aicoder/runners/function_calling_agent_runner.py`

必须完成：

- 新增参数归一化 helper
- 禁止 `evt.action_input` 非 dict 时直接置为 `{}`
- 当归一化失败时，必须生成一个可进入 observation 链路的失败结果
- 必须保留原始 `raw_tool_calls`，便于 step 追踪

### `aicoder/parsers/function_call_parser.py`

必须完成：

- 保持“尽量解析 JSON，失败保留 raw”的职责边界
- 禁止把工具 schema 逻辑塞进 parser
- 如需补充 raw 信息，允许增强 `ParserEvent.raw`

### `aicoder/tools/executor.py`

必须完成：

- 审核所有失败出口，确保都返回 `ToolResult`
- 若发现仍有异常能绕开 `ToolResult`，必须补齐
- 不得破坏现有重试、超时、审批逻辑

### `aicoder/tools/result.py`

必须完成：

- 明确 `ToolResult.fail()` 的 `output` / `error` 一致性策略
- 必要时补最小 meta 字段，支持 step/history 判定成功失败
- `to_message()` 输出语义必须稳定

### `aicoder/graph/nodes.py`

必须完成：

- 在工具结果返回后，除了写 `tool_observations`，还要有办法同步 step store
- `observe_tool_result()` 必须能区分成功、失败、拒绝
- 不得丢失失败 observation

### `aicoder/agent_history_rebuilder.py`

必须完成：

- 不得再把“observed”简单等同于成功
- 必须根据 step 中的失败元信息重建 FAILED / REJECTED / Result 三类消息

---

## 8. 测试强约束

本次改造必须新增或更新测试，以下测试项一个都不能少。

## 8.1 FC 参数归一化测试

必须覆盖：

- 单参数工具 + 字符串参数
- 多参数工具 + JSON object 字符串
- 多参数工具 + 普通字符串
- 非法 JSON 字符串
- `arguments` 为 dict
- `arguments` 为非 dict 非 str

## 8.2 ToolExecutor 失败收敛测试

必须覆盖：

- 未知工具
- 缺少必填参数
- handler 抛异常
- 超时
- 用户拒绝
- 权限模式拒绝

## 8.3 Graph observation 测试

必须覆盖：

- 失败结果进入 `tool_observations`
- `observe_tool_result()` 能把失败结果写回消息列表
- 拒绝结果能写回消息列表
- 多工具场景下首个拒绝/错误后的停止行为保持不变

## 8.4 Step store / history rebuild 测试

必须覆盖：

- 成功 observation 重建
- 失败 observation 重建
- 拒绝 observation 重建
- runner 级 error 重建
- FC history 中 tool message 的失败内容正确
- CoT history 中 user observation 的失败内容正确

---

## 9. 验收标准

满足以下全部条件，才算本次改造完成：

1. FC 路径不再把非 dict 参数默认清空为 `{}`
2. 单参数工具可自动包装字符串参数
3. 多参数工具遇到不可归一化参数时，能生成明确 observation
4. 工具失败不会中断正常 Agent 循环
5. 失败 observation 能进入下一轮 prompt
6. step store 能记录工具成功、失败、拒绝三类 observation
7. history rebuild 能正确还原成功、失败、拒绝三类工具消息
8. 所有新增测试通过
9. 现有图工作流测试不回归

---

## 10. 非目标与边界说明

以下事项不属于本次最小改造范围，禁止顺手扩展：

- 不把 `ToolExecutor` 改造成 Dify 风格 `ToolEngine`
- 不把 workflow 调用与 agent 调用完全拆成两套执行器
- 不新增复杂 meta 对象体系替代 `ToolResult`
- 不在本次引入文件附件、二进制 observation、流式工具消息协议
- 不在本次解决所有工具 schema 描述不完整的问题

如果实施过程中发现“单参数工具判断”缺少稳定元数据，应单独记录为后续事项，不得为了绕过这个问题而取消本次参数归一化目标。

---

## 11. 推荐落地策略

推荐采用如下最小策略：

1. 在 FC runner 增加 `_normalize_tool_params(...)`
2. 为归一化失败构造一个内部失败 observation 结果，而不是伪造 `ToolCall`
3. 在 graph 执行工具结果后，把 observation 同步回 step store
4. 在 history rebuild 中改为根据 `tool_meta.success / rejected` 判断展示文案

这个方案改动面最小，且能最大程度复用你当前已有的：

- `ToolExecutor`
- `ToolResult`
- `tool_observations`
- `StepStore`
- `AgentHistoryRebuilder`

---

## 12. 一句话结论

本次最小改造不是“把 Dify 搬进 AiCoder”，而是把 AiCoder 已有的正确主干补齐到可稳定自纠错、可重建、可测试的状态。
