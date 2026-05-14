# aiCoder 三模式重构方案 v1.1（实现级任务拆解）
版本：v1.1
目标读者：执行型编码 Agent（如 GLM）
执行要求：强约束、按阶段提交、每阶段必须可运行、可测试、可回退

---

## 0. 总目标

本次重构只做以下 5 件事：

1. 修复 `Function Calling` 模式下的结构化工具调用上下文回灌问题
2. 将 `sniff / plan / act` 统一为“同一条 loop + 三套模式配置”
3. 引入统一的 `Context Packer`
4. 引入 mode-aware 的上下文预算策略
5. 为后续 repo map / compaction 升级预留稳定接口

---

## 1. 强约束

### 1.1 必须遵守
1. 不允许移除 LangGraph 主链
2. 不允许删除现有 `CotAgentRunner` 和 `FunctionCallingAgentRunner`
3. 不允许一次性大重构所有模块，必须按阶段实施
4. 每个阶段结束后，测试必须可运行
5. 每个阶段必须保持 CLI/RPC 基本行为不崩
6. 所有新增逻辑优先通过新增模块接入，少改旧模块
7. 不允许把 `plan` 再做成单次回答模式
8. 不允许在 FC runner 下继续把 tool result 统一降级成普通 user 文本
9. 不允许把模式差异只写在 prompt 里，必须落到配置结构
10. 不允许引入外部大型依赖，除非明确需要

### 1.2 暂时禁止
1. 禁止引入完整 event sourcing 重写
2. 禁止引入 subagent 编排大改
3. 禁止引入 tree-sitter repo map 全量迁移
4. 禁止删除现有 `message_builder.py`
5. 禁止改动 TUI 协议字段含义，除非兼容旧字段

### 1.3 代码风格要求
1. 新模块必须单一职责
2. 每个新模块必须有最少单测
3. 所有 mode 判断必须集中，禁止到处散写 `"plan"` / `"sniff"` / `"act"`
4. 所有 LLM message 构造必须走统一入口，禁止 graph node 内临时拼装多套格式
5. 新增 dataclass / TypedDict 优先，不要继续到处传裸 dict

---

## 2. 目标结果（完成定义）

当 v1.1 完成时，系统必须满足：

1. `sniff / plan / act` 三模式都通过统一 loop 执行
2. `plan` 模式允许只读工具循环，不再是一轮直接结束
3. `Function Calling` runner 的下一轮上下文里，保留：
   - assistant tool_calls
   - tool message/tool_call_id 对应结果
4. `CoT` runner 继续保留文本回灌，不受影响
5. 存在统一 `ContextPacker`
6. 存在统一 `MessageConversion`
7. 存在统一 `ModeConfig`
8. graph 节点不再负责多套 message 拼装细节
9. 至少有一版轻量 mode-aware budget policy
10. 现有核心测试通过，新增测试覆盖新逻辑

---

## 3. 目录级改造方案

### 3.1 新增目录与文件

新增以下文件：

- `aicoder/modes/config.py`
- `aicoder/modes/__init__.py`
- `aicoder/messages/types.py`
- `aicoder/messages/conversion.py`
- `aicoder/context/packer.py`
- `aicoder/context/policies.py`
- `aicoder/tests/test_mode_config.py`
- `aicoder/tests/test_message_conversion.py`
- `aicoder/tests/test_context_packer.py`

### 3.2 可选预留文件
先创建空壳或最小实现：

- `aicoder/context/repo_map.py`

---

## 4. 分阶段实施

---

# 阶段 1：引入 ModeConfig，统一模式定义

## 4.1 目标
把模式差异从“散落在 prompt / permission / workflow 中”收敛成一个中心配置模块。

## 4.2 要做的事

### 新建 `aicoder/modes/config.py`
定义以下结构：

```python
from dataclasses import dataclass
from typing import Literal

ModeName = Literal["sniff", "plan", "act"]

@dataclass(frozen=True)
class MemoryPolicy:
    repo_map_tokens: int
    history_tokens: int
    focused_file_tokens: int
    tool_trace_tokens: int
    enable_summary: bool = False
    enable_prune: bool = False

@dataclass(frozen=True)
class ModeConfig:
    name: ModeName
    label: str
    editable: bool
    visible_tools: frozenset[str]
    shell_policy: str
    prompt_style: str
    output_style: str
    memory_policy: MemoryPolicy
```

### 在 `config.py` 中定义三个模式
必须定义：

- `SNIFF_MODE`
- `PLAN_MODE`
- `ACT_MODE`

要求：
- `sniff` 和 `plan` 的 `editable=False`
- `act` 的 `editable=True`
- 三者 `visible_tools` 不同
- 三者 `memory_policy` 不同

### 在 `config.py` 中暴露函数
必须有：

- `get_mode_config(mode: str) -> ModeConfig`
- `is_read_only_mode(mode: str) -> bool`

### 修改现有模块
修改：
- `aicoder/mode_definitions.py`
- `aicoder/permission_modes.py`

要求：
1. 旧逻辑尽量复用新 `ModeConfig`
2. 不允许旧模块继续单独发明 mode 语义
3. `mode_definitions.py` 允许保留对外兼容 API，但内部应转向 `get_mode_config()`

## 4.3 必须新增测试
新增 `aicoder/tests/test_mode_config.py`

至少覆盖：
1. 三模式都存在
2. `sniff/plan` 为只读
3. `act` 可编辑
4. memory policy 存在且三者不完全相同
5. `permission_modes.py` 行为与新配置一致

## 4.4 验收标准
1. 所有旧测试仍通过
2. 新测试通过
3. 没有地方再硬编码重复 mode 语义而绕开 `ModeConfig`

---

# 阶段 2：引入 Message 中间结构与统一转换层

## 5.1 目标
建立“执行/存储态 -> LLM message”的统一转换层，修复 FC runner 的结构化回灌问题。

## 5.2 要做的事

### 新建 `aicoder/messages/types.py`
定义最小中间结构，建议使用 dataclass：

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class AssistantText:
    content: str

@dataclass
class UserText:
    content: str

@dataclass
class ToolCallRecord:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    thought: str = ""

@dataclass
class ToolResultRecord:
    tool_call_id: str
    tool_name: str
    success: bool
    content: str
    is_error: bool = False

StoredItem = AssistantText | UserText | ToolCallRecord | ToolResultRecord
```

要求：
1. 不要一次做太复杂
2. 先只覆盖 FC / CoT 当前必需对象
3. 保持类型清晰

### 新建 `aicoder/messages/conversion.py`
必须提供两个核心函数：

- `build_llm_messages_for_fc(items: list[StoredItem]) -> list[dict]`
- `build_llm_messages_for_cot(items: list[StoredItem]) -> list[dict]`

#### FC 规则
必须满足：
1. `AssistantText` -> assistant content
2. `ToolCallRecord` -> assistant with `tool_calls`
3. `ToolResultRecord` -> tool message with `tool_call_id`
4. 相同 step 的 `AssistantText + ToolCallRecord` 允许组成一个 assistant message
5. 不能把 FC tool result 转成 `[tool] Result:` 普通 user 文本

#### CoT 规则
必须满足：
1. `AssistantText` -> assistant text
2. `ToolCallRecord` -> assistant text中可包含动作描述，或由上层决定
3. `ToolResultRecord` -> user observation text
4. 保持当前 CoT 兼容

### 修改 `aicoder/agent_history_rebuilder.py`
目标：
- 让 `build_for_fc()` 优先使用新转换层的规则
- 保持原测试语义基本一致
- 不要直接散写 tool message 结构

### 修改 `aicoder/graph/nodes.py`
重点是这两个地方：

1. `_model_node_via_runner()`
2. `observe_tool_result()`

要求：
- FC 路径不要再把 tool result 一律文本化加入 `messages`
- FC 路径必须保留结构化 tool result 链路
- CoT 路径仍可沿用文本 observation 逻辑

最稳做法：
- 在 state 中区分保存：
  - `llm_items`
  - 或最小限度保存结构化 `pending_tool_calls` / `tool_observations`
- 由 conversion 层负责最终转成 LLM message 列表

### 修改 `aicoder/runners/function_calling_agent_runner.py`
要求：
1. `run_step()` 返回的结果能带出稳定 tool_call_id
2. 不要只保留 tool name/params，最好保留 call id
3. 如果现有 parser 没提供 id，就用 step.id + index 生成稳定 id

必要时扩展 `StepResult`

### 修改 `aicoder/runners/base_agent_runner.py`
如果需要，扩展 `StepResult`：

```python
tool_calls: list[ToolCall]
tool_call_ids: list[str]
```

或新增更结构化字段，但要保持最小改动。

## 5.3 必须新增测试
新增 `aicoder/tests/test_message_conversion.py`

覆盖：
1. FC：tool call -> tool result -> next round message 结构正确
2. FC：多个 tool call 时 `tool_call_id` 对应正确
3. CoT：tool result 仍转成文本 observation
4. 失败结果在 FC 下仍是结构化 tool message，不是普通 user 文本

如果已有相关 graph 测试，可补充：
- `test_fc_messages_preserve_tool_call_structure`
- `test_cot_messages_remain_textual`

## 5.4 验收标准
1. FC runner 的消息链路结构化正确
2. CoT runner 无回归
3. graph 节点不再自行承担两套拼接逻辑
4. 测试通过

---

# 阶段 3：引入 ContextPacker

## 6.1 目标
把上下文打包从多个地方的隐式拼接，收敛到一个统一入口。

## 6.2 要做的事

### 新建 `aicoder/context/policies.py`
定义预算结构：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ContextBudget:
    repo_map_tokens: int
    history_tokens: int
    focused_file_tokens: int
    tool_trace_tokens: int
    reserve_tokens: int = 4096
```

提供函数：

- `get_context_budget_for_mode(mode: str) -> ContextBudget`

要求：
- 值来自 `ModeConfig.memory_policy`
- 不允许在其他模块到处手写预算

### 新建 `aicoder/context/packer.py`
定义：

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class PackedContext:
    system_messages: list[dict[str, Any]]
    conversation_messages: list[dict[str, Any]]
```

提供主入口：

- `pack_context(coder, user_input: str, mode: str, runner_type: str, state_messages: list[dict] | None = None) -> PackedContext`

要求：
1. `system_messages` 必须至少包含：
   - system prompt
   - runtime state
   - mode attachment
2. `conversation_messages` 必须来自统一逻辑
3. 允许初版先继续调用：
   - `build_system_messages()`
   - `build_runtime_state_messages()`
   - `build_mode_messages()`
4. 但必须把调用集中到 `ContextPacker`

### ContextPacker 初版职责
必须做：
1. 统一调用系统消息构建
2. 读取 `done_messages`
3. 读取 `cur_messages`
4. 统一应用 mode budget
5. 为后续 repo map / compaction 预留插槽

可以先不做复杂 repo map，只保留接口：
- `build_repo_context(...) -> list[dict]`

### 修改 `aicoder/graph/nodes.py`
修改：
- `prepare_context()`
- `model_node()`

要求：
1. `prepare_context()` 使用 `pack_context()`
2. 不再直接散落调用 `_build_llm_messages()`
3. `_build_llm_messages()` 可以保留给过渡期使用，但新主链应走 `ContextPacker`

### 修改 `aicoder/coders/message_builder.py`
要求：
1. 保留底层函数
2. 不再把它当成最终总装器
3. 添加注释说明：最终组装由 `ContextPacker` 完成

## 6.3 必须新增测试
新增 `aicoder/tests/test_context_packer.py`

覆盖：
1. `sniff` / `plan` / `act` 打包出的 system 部分不同
2. `runtime state` 一定存在
3. `mode attachment` 一定存在或按模式为空
4. `PackedContext` 结构正确
5. budget 调用路径正常

## 6.4 验收标准
1. graph 主链已接入 `ContextPacker`
2. 上下文拼装入口统一
3. 测试通过

---

# 阶段 4：统一三模式 loop，移除 plan 单步直出

## 7.1 目标
让 `sniff / plan / act` 都进入统一 loop，差异由 ModeConfig 和权限控制。

## 7.2 要做的事

### 修改 `aicoder/graph/nodes.py`
修改 `route_mode()`：

当前不要再区分：
- `plan -> plan node`
- `else -> act`

改为：
- 三种模式都走 loop 路径

### 修改 `aicoder/graph/workflow.py`
重构建议：

#### 旧结构
- `prepare_context -> route_mode`
- `plan -> request_plan_approval -> END`
- `act -> model -> parse -> permission -> execute -> observe -> summarize`

#### 新结构（v1.1）
- `prepare_context -> model -> parse -> permission -> execute -> observe -> summarize`

说明：
- `plan_node` 和 `request_plan_approval` 可以保留但不再作为主路径
- 如需兼容，先保留节点但不走默认分支

### 完成判定策略
在 `aicoder/graph/nodes.py` 中新增基于 mode 的完成判定函数，例如：

- `should_finish_for_mode(state, coder) -> bool`

要求：
- `sniff`：无 tool calls 且已有足够回复时可结束
- `plan`：无 tool calls 时结束，但允许前面读工具循环
- `act`：保持当前逻辑

最小做法：
- 保持 route_after_model 基本逻辑
- 但去掉 `plan` 单步专用路径

### 修改 `aicoder/permission_modes.py`
确保：
- `plan` 和 `sniff` 的只读能力保持一致或按配置区分
- 两者都允许 read-only shell
- `plan` 不再因 workflow 限制而无法探索

## 7.3 必须新增/修改测试
重点修改：

- `aicoder/tests/test_graph_workflow.py`
- `aicoder/tests/test_graph_permissions.py`

必须新增：
1. `test_plan_mode_can_execute_read_only_tools`
2. `test_plan_mode_still_denies_edit_tools`
3. `test_sniff_mode_uses_same_loop_but_read_only`
4. `test_plan_mode_no_longer_short_circuits_to_single_answer`

## 7.4 验收标准
1. `plan` 可以走只读工具循环
2. `sniff` 仍只读
3. `act` 不回归
4. graph 测试通过

---

# 阶段 5：补轻量级 tool trace 与失败反馈改进

## 8.1 目标
借鉴 Aider 的 reflected_message 思想，改进 `act` 模式下的失败闭环，但不引入完整反思系统重写。

## 8.2 要做的事

### 扩展 `aicoder/agent_step_store.py`
在不大改架构的前提下，增强 step 数据：

至少补充：
- `tool_calls: list[dict]` 或等价字段
- `tool_results: list[dict]` 或等价字段
- `summary: str = ""`

如果不方便改 dataclass，允许新增 metadata 字段，但必须结构化。

### 修改 `aicoder/graph/nodes.py`
在 tool 执行失败时，构造更丰富 observation，而不是只给简短 error。

失败 observation 至少应包含：
- tool 名称
- success/failure
- error 摘要
- 是否部分成功
- 推荐下一步（如果能推断）

### 修改 `aicoder/tools/executor.py`
如有必要，增强 `ToolResult.meta`

至少鼓励写入：
- `tool_name`
- `success`
- `rejected`
- `error_type`
- `summary`

## 8.3 测试
补充：
- `aicoder/tests/test_graph_observation.py`
- `aicoder/tests/test_tool_executor.py`

新增：
1. 失败 observation 结构更完整
2. act 模式下错误可被下一轮上下文使用
3. CoT/FC 都能消费该错误信息

## 8.4 验收标准
1. 工具失败回灌不再只有单薄字符串
2. 测试通过

---

# 阶段 6：预留简化 Repo Context 接口（只做骨架）

## 9.1 目标
为后续迁移 Aider repo map 做接口，不在 v1.1 完成完整实现。

## 9.2 要做的事

### 新建 `aicoder/context/repo_map.py`
只实现最小接口：

- `build_repo_context(coder, mode: str, budget_tokens: int) -> list[dict]`

初版允许：
1. 不做 PageRank
2. 仅返回空列表或基于现有 file tree / repo map 的轻量结果
3. 但函数必须真实接入 `ContextPacker`

### 修改 `aicoder/context/packer.py`
要求：
- 调用 `build_repo_context(...)`
- 让 `sniff` / `plan` / `act` 通过 budget 决定 repo context 规模

## 9.3 测试
新增最小测试：
1. `sniff` 比 `act` 拥有更大 repo budget
2. `ContextPacker` 调用 repo context builder

## 9.4 验收标准
1. 接口已存在
2. 主链已预留接入点
3. 后续可平滑升级

---

## 5. 具体文件修改清单

### 必改文件
- `aicoder/mode_definitions.py`
- `aicoder/permission_modes.py`
- `aicoder/graph/nodes.py`
- `aicoder/graph/workflow.py`
- `aicoder/agent_app_runner.py`
- `aicoder/agent_history_rebuilder.py`
- `aicoder/runners/base_agent_runner.py`
- `aicoder/runners/function_calling_agent_runner.py`
- `aicoder/coders/message_builder.py`
- `aicoder/agent_step_store.py`
- `aicoder/tools/executor.py`

### 新增文件
- `aicoder/modes/config.py`
- `aicoder/modes/__init__.py`
- `aicoder/messages/types.py`
- `aicoder/messages/conversion.py`
- `aicoder/context/policies.py`
- `aicoder/context/packer.py`
- `aicoder/context/repo_map.py`
- `aicoder/tests/test_mode_config.py`
- `aicoder/tests/test_message_conversion.py`
- `aicoder/tests/test_context_packer.py`

---

## 6. 提交粒度要求

GLM 必须按以下粒度提交修改，不允许一把梭：

1. `feat: add mode config and centralize mode semantics`
2. `feat: add message conversion layer for fc and cot`
3. `refactor: route graph context building through context packer`
4. `feat: unify sniff plan act into shared model loop`
5. `feat: enrich tool failure observations and step data`
6. `chore: add repo context extension points`

每一步都要：
- 修改代码
- 跑测试
- 输出变更说明
- 如果失败，先修到当前阶段通过，再做下一阶段

---

## 7. 每阶段完成后的测试命令

优先运行：

```bash
pytest aicoder/tests/test_mode_config.py
pytest aicoder/tests/test_message_conversion.py
pytest aicoder/tests/test_context_packer.py
pytest aicoder/tests/test_graph_workflow.py
pytest aicoder/tests/test_graph_permissions.py
pytest aicoder/tests/test_graph_observation.py
pytest aicoder/tests/test_tool_executor.py
```

阶段性回归：

```bash
pytest
```

如果全量太慢，至少运行：

```bash
pytest aicoder/tests/test_graph_workflow.py aicoder/tests/test_graph_permissions.py aicoder/tests/test_message_builder.py aicoder/tests/test_tool_executor.py
```

---

## 8. GLM 执行时的输出要求

GLM 每完成一个阶段，必须输出：

### 阶段报告模板

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

1. 不要擅自删掉旧测试
2. 不要跳过测试直接进入下一阶段
3. 不要把 `plan` 改成“依然单次回答，只是换个 prompt”
4. 不要为了省事让 FC 和 CoT 共用文本回灌
5. 不要把 ContextPacker 写成旧 `message_builder.py` 的简单别名
6. 不要把 `ModeConfig` 只做成常量文件而不接入旧逻辑
7. 不要先上复杂 repo map 全量实现
8. 不要顺手改 TUI 协议和 RPC 结构，除非必要且兼容
9. 不要引入大量新依赖
10. 不要在 graph node 中继续散写 mode-specific message 拼接

---

## 10. 实施优先级总结

严格按这个顺序做：

1. `ModeConfig`
2. `MessageConversion`
3. `ContextPacker`
4. 三模式统一 loop
5. tool failure feedback
6. repo context extension point

不得调整顺序，除非某一步的前置条件被代码现实阻塞，并在报告中明确说明原因。

---

## 11. 最终交付标准

完成后必须满足：

1. 新增模块存在且被主链真实使用
2. FC 下 tool 调用上下文结构化保留
3. `plan` 模式不再短路
4. 三模式共享 loop
5. 上下文拼装统一入口生效
6. 测试通过
7. 代码可继续承接后续 `OpenHands` 分析结果
