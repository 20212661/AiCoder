# LangChain Runtime 迁移总体计划

## 1. 背景与目标

当前 aiCoder 后端已经是一个本地 Agent 后端，而不是普通业务后端。它包含以下核心能力：

- CLI / TUI 入口
- JSON-RPC over stdio 通信
- 模型调用
- 工具解析与执行
- 本地文件、Shell、Git 操作
- sniff / plan / act 模式权限
- 用户审批
- 会话保存与恢复
- LangGraph 工作流

本次迁移目标不是用 LangChain 全量替换现有后端，而是：

```text
用 LangChain / LangGraph 替代通用 Agent Runtime 能力；
保留 aiCoder 自己的 TUI/RPC、本地安全执行、代码理解工具和权限边界。
```

最终形态：

```text
aicoder-tui
  -> rpc_io.py
  -> Runtime Router
  -> legacy runtime / langchain runtime
  -> LangChain Agent
  -> LangChain StructuredTool
  -> aiCoder Safe Executor
  -> 文件系统 / Git / Shell / tree-sitter / grep-ast
```

## 2. 核心原则

1. 默认行为不变。

   初期必须保留现有 runtime 作为默认实现。LangChain runtime 只能通过显式参数启用。

2. 先旁路接入，再逐步切换。

   不允许第一批改动直接替换 `workflow.py`、`executor.py` 或 `rpc_io.py` 的默认路径。

3. 安全边界不交给模型。

   文件写入限制、路径安全、Shell 命令策略、用户拒绝后的停止行为，必须继续由确定性代码控制。

4. 真实工具执行继续走现有 ToolExecutor。

   LangChain Tool 只做 schema、参数入口和 Agent runtime 适配，不直接读写文件或执行命令。

5. 每个阶段都要可回退。

   任一阶段出现问题时，用户仍可通过 legacy runtime 使用现有功能。

## 3. 建议迁移阶段

### 阶段 1：新增 LangChain Runtime 旁路

目标：

- 新增 `aicoder/langchain_runtime/`
- 新增 ChatLiteLLM 模型适配
- 新增 LangChain Agent 构建入口
- 新增 `--runtime legacy|langchain`
- 默认 runtime 保持 `legacy`
- 初期只要求 `--runtime langchain --message` 可运行

不做：

- 不拆 `executor.py`
- 不改 `rpc_io.py`
- 不替换 `workflow.py`
- 不接 interrupt
- 不接 checkpointer
- 不默认启用 LangChain runtime

### 阶段 2：用 Pydantic + StructuredTool 包装现有工具

目标：

- 为核心工具新增 Pydantic 参数模型
- 将 `read_file`、`write_file`、`edit_file`、`search_files`、`run_shell` 包装为 LangChain `StructuredTool`
- StructuredTool 内部调用 `coder.tool_executor.execute(ToolCall(...))`

保留：

- `ToolHandler.validate_params()`
- `ToolExecutor` 权限、审批、重试、超时、写入限制

### 阶段 3：LangChain Agent Runner 旁路运行

目标：

- 新增 LangChain runner
- 允许 `aicoder --runtime langchain --message "..."` 走 LangChain Agent
- legacy runtime 仍为默认
- TUI `--serve` 初期仍走 legacy

### 阶段 4：引入低风险 Middleware

目标：

- 接入模型调用次数限制
- 接入工具调用次数限制
- 接入模型重试
- 接入工具重试

暂不接：

- HumanInTheLoopMiddleware
- LangGraph interrupt
- checkpointer

原因：

审批和恢复会牵动 TUI/RPC 会话模型，应该单独阶段处理。

### 阶段 5：Structured Output

目标：

- 定义 `AICoderResponse`
- LangChain runtime 返回稳定结构化结果
- CLI 初期仍展示 `summary`
- 为后续 TUI/RPC 结构化展示做准备

### 阶段 6：审批与 Interrupt 适配

目标：

- 保留 `rpc_io.py` 的 `approval/request` 和 `approval/respond`
- 将 LangGraph interrupt / HITL middleware 接到现有 TUI 审批协议
- 用户拒绝后必须停止后续危险工具

第一批 interrupt 工具：

- `write_file`
- `edit_file`
- `run_shell`

### 阶段 7：Checkpointer 与状态恢复

目标：

- 将 RPC session id 映射为 LangGraph `thread_id`
- 使用 SQLite checkpointer 保存 Agent 状态
- 支持 interrupt 后恢复
- 支持进程重启后的最小恢复路径

注意：

有副作用的工具必须避免恢复时重复执行。

### 阶段 8：收薄 executor.py

目标：

将当前 `executor.py` 逐步拆成更明确的安全执行边界：

```text
aicoder/tools/safe_executor.py
aicoder/tools/policy_engine.py
aicoder/tools/approval_adapter.py
aicoder/tools/executor.py
```

职责：

- `safe_executor.py`：真实文件、Shell、Git 执行
- `policy_engine.py`：sniff / plan / act 权限、allow / ask / deny
- `approval_adapter.py`：CLI / RPC / LangGraph 审批适配
- `executor.py`：兼容旧接口，内部组合上述模块

## 4. 模块替代边界

| 当前模块 | 迁移策略 | 说明 |
| --- | --- | --- |
| `rpc_io.py` | 保留 | TUI/RPC 是产品特色，不改成 HTTP 服务 |
| `workflow.py` | 暂不替换 | 先新增旁路 runtime，后续再评估 |
| `llm.py` | 适配 | LiteLLM 继续负责多模型，ChatLiteLLM 负责 LangChain 接入 |
| `executor.py` | 先保留，后收薄 | 初期所有真实工具执行仍走 ToolExecutor |
| `permission_modes.py` | 保留 | mode 权限是安全边界 |
| `tools/*` | 包装 | 包成 LangChain StructuredTool |
| `tree-sitter / grep-ast / gitpython` | 保留 | 这是代码理解能力，不替换 |

## 5. 第一批 PR 范围

第一批只做：

```text
Add experimental LangChain runtime adapter
```

包含：

- 新增 `langchain-litellm` 依赖
- 新增 `aicoder/langchain_runtime/`
- 实现 `model.py`
- 实现 `schemas.py`
- 实现 `tools.py`
- 实现 `agent.py`
- 新增 `--runtime legacy|langchain`
- 默认 `legacy`
- 初期只要求 `--runtime langchain --message` 可运行
- 增加最小单测

不包含：

- 不拆 `executor.py`
- 不改 `rpc_io.py`
- 不替换 `workflow.py`
- 不接 middleware
- 不接 interrupt
- 不接 checkpointer
- 不默认启用 LangChain runtime

## 6. 第一批验收标准

1. `aicoder --message "hello"` 仍走旧链路。
2. `aicoder --runtime langchain --message "hello"` 走新链路。
3. LangChain Tool 内部仍调用 `coder.tool_executor.execute()`。
4. 现有权限、审批、文件写入限制、Shell 限制仍生效。
5. 单测覆盖工具包装与 runtime 参数解析。
6. 现有测试不因新增模块回归。

## 7. 风险与控制

### 风险：LangChain 版本 API 与预期不一致

控制：

- 第一阶段只使用 `ChatLiteLLM`、`StructuredTool`、`create_agent` 等基础 API
- middleware / interrupt / checkpoint 后置

### 风险：工具异常语义变化

控制：

- `ToolResult.success == False` 时，LangChain wrapper 抛出 `RuntimeError`
- 不吞掉 `ToolExecutor` 的错误消息

### 风险：默认行为回归

控制：

- 默认 runtime 必须是 `legacy`
- `--serve` 初期不切 LangChain
- 不改现有 `workflow.py` 默认路径

### 风险：安全边界被绕过

控制：

- LangChain Tool 禁止直接读写文件
- 所有工具调用必须进入 `ToolExecutor`
- 单测检查 wrapper 调用了 executor

