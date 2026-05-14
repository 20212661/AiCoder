# LangChain Runtime — 当前状态

> 最后更新：2026-05-14
> 版本：v0.8.0

## 已完成能力

### Phase 1: 实验性 LangChain runtime 旁路

- `aicoder --runtime langchain --message "hello"` 可走 LangChain Agent
- 默认 `--runtime legacy` 不受影响
- `--serve` 不受影响
- 5 个核心工具通过 `StructuredTool` 包装，所有执行仍走 `ToolExecutor`
- 工具参数 schema 与实际 handler 一致（`edit_file` 用 `search`/`replace`，`search_files` 用 `regex`/`file_pattern`）
- 单测覆盖工具包装、失败抛错、CLI 参数解析

### Phase 2: Structured Output + Middleware 构建层

- `AICoderResponse` schema 已定义（summary, changed_files, commands_run, needs_approval, error）
- `create_react_agent(response_format=AICoderResponse)` 已接入
- `extract_langchain_response_text()` 优先读取 `structured_response.summary`，fallback 到最后 message content
- `build_middleware()` 构建层已就位，支持未来的 middleware 接入

### Phase 2+: 运行时可观测性

- `build_langchain_agent()` 记录 `structured_response` 是否启用、middleware 数量
- `build_langchain_tools()` 记录注册的工具名列表
- `--runtime langchain` 非 `--message` 模式进入 CLI 交互循环（Phase 5 实现）
- 冒烟测试覆盖 legacy/langchain 路由互不影响

### Phase 3: 工具错误处理 middleware

- `handle_tool_errors` middleware 通过 `wrap_tool_call` 包装所有工具调用
- 工具异常被转换为 `ToolMessage`（而非未处理异常冒泡到 agent 外层）
- `format_tool_error_message()` 保留语义错误类别（用户拒绝 / 安全阻止 / 权限拒绝 / 一般执行失败）
- Agent builder 通过 `_agent_accepts_kwarg("middleware")` 动态检查是否传入 middleware
- 工具 schema 确认无 `config` / `runtime` LangChain 保留参数名
- 约束文档 `docs/langchain-runtime-tools-contract.md` 已建立

### Phase 4: Session 持久化

- 普通消息（`--message`）成功后写入 session JSON
- 保存内容与 legacy runtime 一致：`{role: user/assistant}` 消息对
- `cur_messages` → `done_messages` → `_save_session()` 路径完整

### Phase 5: CLI 交互模式

- `aicoder --runtime langchain`（无 `--message`）进入 CLI 交互循环
- 支持 `/quit`、`/exit` 退出循环
- 支持 `/clear` 清空 `done_messages` 和 `cur_messages`，输出确认
- 未支持的 slash command 输出 warning，不调用 agent，不保存 session
- 每轮调用 `run_langchain_agent()`，与 `--message` 一次性模式执行逻辑一致
- `KeyboardInterrupt` 处理与 legacy runtime 一致（双击退出）
- `EOFError`（Ctrl-D）退出循环
- 每轮成功后保存 session JSON（通过 `persist_langchain_turn()`）
- agent 异常时 `tool_error` 输出错误，不保存 session，循环继续

## 支持矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| `--runtime langchain --message` | ✅ 已支持 | 单轮执行，成功后写入 session JSON |
| `--runtime langchain` CLI 交互 | ✅ 已支持 | 交互循环，每轮保存 session |
| `/quit`、`/exit`、`/clear` | ✅ 已支持 | 通过 `interactive.py` 命令路由 |
| Session JSON 写入 | ✅ 已支持 | 普通消息成功后写入 |
| 工具执行走 ToolExecutor | ✅ 已支持 | 所有工具经 `StructuredTool` → `ToolExecutor` |
| TUI `--serve langchain` 交互 | ❌ 未支持 | `rpc_io` 循环未适配 langchain runtime |
| Streaming | ❌ 未支持 | 使用同步 `agent.invoke()`，无逐 token 输出 |
| interrupt / checkpointer | ❌ 未支持 | 后续阶段入口 |
| middleware 限流/重试 | ⚠️ 降级 | `langchain` 版本缺少对应模块，降级为空 |

## 当前降级点

| 功能 | 状态 | 原因 |
|------|------|------|
| handle_tool_errors | 已接入 | `langchain.agents.middleware.wrap_tool_call` 可用 |
| ModelCallLimitMiddleware | 降级为空 | `langchain` 无 `langchain.middleware` 模块 |
| ToolCallLimitMiddleware | 降级为空 | 同上 |
| ModelRetryMiddleware | 降级为空 | 同上 |
| ToolRetryMiddleware | 降级为空 | 同上 |
| middleware 传入 agent | 条件接入 | `_agent_accepts_kwarg("middleware")` 检查后传入 |
| Structured Output | 已接入 | `create_react_agent` 支持 `response_format` |
| Streaming | 未支持 | 同步 `agent.invoke()`，无逐 token 输出 |
| TUI --serve langchain 交互 | 未支持 | `rpc_io` 循环未适配 langchain runtime |
| interrupt / checkpointer | 未支持 | 后续阶段入口 |

## 后续阶段

- **下一阶段入口：interrupt + checkpointer**
  - `HumanInTheLoopMiddleware` 接入
  - LangGraph `interrupt` 用于工具审批中断
  - `checkpointer` 用于会话状态持久化和恢复

## 回归测试矩阵

| 测试文件 | 测试数 | 覆盖范围 | 运行命令 |
|----------|--------|----------|----------|
| `test_langchain_runtime.py` | 84 | 工具包装、schema、middleware、structured output、session 保存、CLI 参数、交互循环 | `python -m pytest aicoder/tests/test_langchain_runtime.py` |
| `test_session_resume.py` | 19 | session 恢复、消息视图、CoT 格式 | `python -m pytest aicoder/tests/test_session_resume.py` |
| `test_rpc_io.py` | 2 | RPC 输入阻塞、队列命令 | `python -m pytest aicoder/tests/test_rpc_io.py` |
| `test_tool_executor.py` | 17 | 工具执行、权限审批、拒绝处理 | `python -m pytest aicoder/tests/test_tool_executor.py` |

**总计：122 个测试**

运行全部回归：

```bash
python -m pytest aicoder/tests/test_langchain_runtime.py aicoder/tests/test_session_resume.py aicoder/tests/test_rpc_io.py aicoder/tests/test_tool_executor.py
```

## 文件结构

```
aicoder/langchain_runtime/
  __init__.py          # 模块入口
  model.py             # ChatLiteLLM 构建器
  schemas.py           # Pydantic 参数 schema + AICoderResponse
  tools.py             # StructuredTool 包装（走 ToolExecutor）
  agent.py             # create_react_agent 构建 + 结果解析
  middleware.py         # middleware 构建层（handle_tool_errors + rate limit/retry 降级）
  session.py           # session 持久化助手（persist_langchain_turn）
  interactive.py       # CLI 交互循环（run_langchain_interactive）

aicoder/tests/test_langchain_runtime.py  # 84 个测试
aicoder/tests/test_session_resume.py     # 19 个测试
aicoder/tests/test_rpc_io.py             # 2 个测试
aicoder/tests/test_tool_executor.py      # 17 个测试

docs/langchain-runtime-tools-contract.md         # 工具约束文档
docs/langchain-runtime-interactive-loop-plan.md   # 交互循环设计文档
docs/langchain-runtime-status.md                  # 本文档
```

## 禁止事项（当前仍遵守）

1. 不修改 `rpc_io.py`
2. 不替换 `workflow.py`
3. 不拆 `executor.py`
4. 不默认启用 langchain runtime
5. 不修改 `--serve` 默认行为
6. 不接入 `HumanInTheLoopMiddleware`
7. 不接入 LangGraph `interrupt`
8. 不接入 `checkpointer`
9. 不直接读写文件绕过 `ToolExecutor`
10. 不直接运行 `subprocess` 绕过 `ToolExecutor`

## 启用方式

```bash
# LangChain runtime 单轮执行
aicoder --runtime langchain --message "your question"

# LangChain runtime CLI 交互模式
aicoder --runtime langchain

# 默认 legacy runtime（不变）
aicoder --message "your question"
aicoder --serve
```
