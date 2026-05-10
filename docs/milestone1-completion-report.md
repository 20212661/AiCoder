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

---

# 里程碑 1 完成报告 — 2026-05-09

## 一句话说明

系统默认通过 LangGraph Runtime 执行，`Coder.run()` 委托给 `AgentRuntime.run_user_turn()`，legacy 主循环保留但不再是默认路径。

## 完成项

### 任务 1：建立后端整改基线
- 阅读了 7 个核心文件，梳理出两条执行链的完整对照
- 产出基线文档：`docs/baseline-backend-state.md`
- pytest 基线：351 passed

### 任务 2：输出后端主链统一设计
- 确定保留 LangGraph Runtime 作为唯一主链
- 明确了迁移/废弃/保留的逻辑分界
- 产出设计文档：`aicoder/docs/runtime-unification.md`

### 任务 3：收口 /run 和 /git
- `commands.py` 的 `cmd_run()` 和 `cmd_git()` 不再直接 `subprocess.run`
- 改为构造 `ToolCall("run_shell", ...)` 交给 `tool_executor.execute()`
- 统一进入审批/超时/结果处理链
- 新增 7 个测试覆盖（成功/失败/拒绝场景）
- 清理了不再使用的 `import subprocess, shlex`

### 任务 4：统一权限入口并收紧默认策略
- 从 `ACT_MODE_AUTO_APPROVED_COMMANDS` 移除 `rm`, `rmdir`, `mv`, `cp`, `sed`
- 仅保留 `mkdir`, `touch` 作为自动放行命令
- 新增 5 个测试验证收紧后的行为
- 产出权限矩阵文档：`docs/permission-matrix.md`

### 任务 5：移除或降级 legacy 主循环职责
- `Coder.run()` 默认走 `AgentRuntime`，不再需要 `AICODER_LANGGRAPH_RUNTIME` 环境变量
- 迁移分层上下文裁剪策略到 `graph/nodes._trim_messages()`（3 级：LLM 总结 → ContextManager → 紧急截断）
- 迁移 `summarize_if_needed()` 到 `summarize_node()`
- 清理 `_send_message_inner()` 和 `format_messages()` 中的 3 处 debug stderr 写入
- Legacy `_send_message_inner()` 保留但不再是默认主路径

### 任务 6：补后端验证闭环
- pytest: **360 passed** in 29.02s（新增 9 个测试）
- CLI 入口导入正常
- AgentRuntime 导入正常
- Graph 构建正常（10 个节点）

## 修改文件清单

| 文件 | 改动 |
|------|------|
| `aicoder/commands.py` | `/run` `/git` 走工具系统，移除 subprocess 直接调用 |
| `aicoder/permission_modes.py` | 收紧自动放行命令集合 |
| `aicoder/coders/base_coder.py` | 默认走 LangGraph，清理 debug 输出 |
| `aicoder/graph/nodes.py` | 增强 `_trim_messages()` 和 `summarize_node()` |
| `aicoder/tests/test_commands.py` | 新增 `/run` `/git` 工具系统测试 |
| `aicoder/tests/test_permission_modes.py` | 新增权限收紧测试 |
| `docs/baseline-backend-state.md` | 新建基线文档 |
| `aicoder/docs/runtime-unification.md` | 新建设计文档 |
| `docs/permission-matrix.md` | 新建权限矩阵文档 |

## 未完成项 / 剩余风险

1. **Legacy `_send_message_inner()` 仍保留**：代码未删除，仅作为降级备用。后续可完全移除。
2. **`_process_legacy_edits()` 未迁移**：wholefile/editblock 编辑格式的后处理仍在 legacy 路径中。需要确认 graph 流程中是否需要保留。
3. **RPC 模式（--serve）兼容性**：`Coder.run()` 改为走 AgentRuntime 后，需要实际测试 RPC IO 兼容性。
4. **`run_one()` 方法不再被调用**：`Coder.run()` 直接委托给 AgentRuntime，`run_one()` 成为死代码，后续可清理。
5. **context_manager 模块**：`_trim_messages()` 引用了 `context_manager.ContextManager`，该模块在迁移前需确认存在且可用。
