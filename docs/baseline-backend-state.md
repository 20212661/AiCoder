# 后端整改基线 — 2026-05-09

## 后端主入口

`aicoder/main.py:main()` — 参数解析 → 配置加载 → Coder 创建 → 进入主循环或 RPC 模式

## 当前存在的双路径

### 路径 A：Legacy Coder 主循环（默认激活）

入口：`Coder.run()` → `run_one()` → `send_message()` → `_send_message_inner()`

执行流程：
1. `format_messages()` 构建消息
2. `main_model.send_completion()` 调用 LLM（流式/非流式）
3. `_process_tool_calls()` 解析 XML 工具调用 → `tool_executor.execute_all()`
4. 最多 5 轮工具循环
5. `_process_legacy_edits()` 处理遗留编辑格式
6. auto_commit + _save_session

触发条件：默认（不需要任何环境变量）

### 路径 B：LangGraph Runtime（需环境变量激活）

入口：`Coder.run()` → `AgentRuntime.run_user_turn()` → graph.invoke()

Graph 节点流水线：
```
prepare_context → route_mode
  → plan: plan_node → request_plan_approval → END
  → act: model_node → route_after_model
    → tools: parse_tool_calls → permission_node → execute_tool_node → observe_tool_result → route_after_observe → (loop/finish)
    → finish: summarize_node → END
```

触发条件：`AICODER_LANGGRAPH_RUNTIME=1`

## 重复职责对照

| 职责 | Legacy 路径 | LangGraph 路径 |
|------|------------|----------------|
| 模型调用 | `_send_message_inner()` | `_call_llm()` / `model_node()` |
| 工具解析 | `_process_tool_calls()` → `parse_xml_tools` | `model_node()` 内 `parse_xml_tools` |
| 工具执行 | `tool_executor.execute_all()` | `execute_tool_node()` → `tool_executor.execute()` |
| 权限判断 | `ToolExecutor._get_permission_decision()` | `permission_node()` → `can_use_tool_in_mode()` |
| 上下文裁剪 | `_trim_context_for_model()` | `_trim_messages()` |
| 持久化 | `_send_message_inner()` 末尾 | `summarize_node()` / `request_plan_approval()` |
| Auto commit | `_send_message_inner()` 末尾 | `summarize_node()` 内 |
| 总结 | `summarize_if_needed()` | 无独立总结（依赖 LLM 最终回复） |

## 当前通过项

- pytest: **351 passed** in 26.60s
- 测试覆盖：tools, permission_modes, approval, graph, commands, models, utils

## 当前风险项

1. **命令绕过**：`/run` 和 `/git`（commands.py L466-501）直接 `subprocess.run`，不走工具系统，绕过审批和超时
2. **危险命令自动放行**：`ACT_MODE_AUTO_APPROVED_COMMANDS` 包含 `rm`, `rmdir`, `mv`, `cp`, `sed`
3. **Debug 残留**：`_send_message_inner()` 有 `[DBG]` stderr 写入（3处）
4. **环境变量切换**：两条核心运行时通过 `AICODER_LANGGRAPH_RUNTIME` 环境变量切换，易造成长期并存
5. **权限分散**：`permission_modes.py` 和 `approval.py` 各自维护安全规则，边界不清晰
