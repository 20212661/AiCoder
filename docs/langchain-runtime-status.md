# LangChain Runtime — 当前状态

> 最后更新：2026-05-14

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
- `--runtime langchain` 非 `--message` 模式给出明确的命令行提示
- 冒烟测试覆盖 legacy/langchain 路由互不影响

### Phase 3: 工具错误处理 middleware

- `handle_tool_errors` middleware 通过 `wrap_tool_call` 包装所有工具调用
- 工具异常被转换为 `ToolMessage`（而非未处理异常冒泡到 agent 外层）
- `format_tool_error_message()` 保留语义错误类别（用户拒绝 / 安全阻止 / 权限拒绝 / 一般执行失败）
- Agent builder 通过 `_agent_accepts_kwarg("middleware")` 动态检查是否传入 middleware
- 工具 schema 确认无 `config` / `runtime` LangChain 保留参数名
- 约束文档 `docs/langchain-runtime-tools-contract.md` 已建立

## 当前降级点

| 功能 | 状态 | 原因 |
|------|------|------|
| handle_tool_errors | 已接入 | `langchain.agents.middleware.wrap_tool_call` 可用 |
| ModelCallLimitMiddleware | 降级为空 | `langchain==1.2.17` 无 `langchain.middleware` 模块 |
| ToolCallLimitMiddleware | 降级为空 | 同上 |
| ModelRetryMiddleware | 降级为空 | 同上 |
| ToolRetryMiddleware | 降级为空 | 同上 |
| middleware 传入 agent | 条件接入 | `_agent_accepts_kwarg("middleware")` 检查后传入 |
| Structured Output | 已接入 | `create_react_agent` 支持 `response_format` |
| 非 `--message` 交互模式 | 不支持 | LangChain runtime 仅支持 `--message` 单轮模式 |

## 文件结构

```
aicoder/langchain_runtime/
  __init__.py          # 模块入口
  model.py             # ChatLiteLLM 构建器
  schemas.py           # Pydantic 参数 schema + AICoderResponse
  tools.py             # StructuredTool 包装（走 ToolExecutor）
  agent.py             # create_react_agent 构建 + 结果解析
  middleware.py         # middleware 构建层（handle_tool_errors + rate limit/retry 降级）

aicoder/tests/test_langchain_runtime.py  # 51 个测试
docs/langchain-runtime-tools-contract.md # 工具约束文档
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
# LangChain runtime（显式启用）
aicoder --runtime langchain --message "your question"

# 默认 legacy runtime（不变）
aicoder --message "your question"
aicoder --serve
```
