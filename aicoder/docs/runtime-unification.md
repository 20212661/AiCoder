# 后端主链统一设计

## 1. 推荐保留的唯一主链

**保留 LangGraph Runtime 作为唯一主链。**

理由：
- 节点化架构，职责边界清晰（model / permission / execute / observe / summarize）
- 已内建 plan/act 模式分支，无需额外逻辑
- 支持 checkpoint 和 interrupt，为后续多轮审批提供基础
- 工具循环由 graph 边条件控制，不依赖手动 for 循环

**废弃 Legacy `_send_message_inner()` 主循环。**

Legacy 链的问题是：模型调用、工具解析、工具执行、持久化全部塞在一个方法里，难以单独测试和替换。

## 2. 迁移计划

### 2.1 需要从 Legacy 迁移到 LangGraph 的逻辑

| 逻辑 | 当前位置 (Legacy) | 迁移目标 | 说明 |
|------|-------------------|----------|------|
| 分层上下文裁剪 | `_trim_context_for_model()` | `nodes._trim_messages()` | Legacy 有 3 级策略（LLM 总结 → ContextManager → 紧急截断），graph 版本只有简单截断 |
| LLM 总结 | `summarize_if_needed()` | `summarize_node()` | 旧消息的 LLM 自动总结，graph 目前缺失 |
| 消息格式化 | `format_messages()` / `message_builder` | `nodes._build_llm_messages()` | 已有对齐，确认一致即可 |

### 2.2 需要废弃的 Legacy 逻辑

| 逻辑 | 位置 | 说明 |
|------|------|------|
| `_send_message_inner()` | `base_coder.py` | Legacy 主循环，由 graph 节点链替代 |
| `_process_tool_calls()` | `base_coder.py` | 工具解析+执行，由 `model_node` + `execute_tool_node` 替代 |
| 环境变量切换 `AICODER_LANGGRAPH_RUNTIME` | `Coder.run()` | 不再需要切换，默认走 LangGraph |
| debug stderr 写入 | `_send_message_inner()` | 3 处 `[DBG]` 写入，清理 |

### 2.3 保留不变的逻辑

| 逻辑 | 位置 | 说明 |
|------|------|------|
| `Coder` 类 | `base_coder.py` | 作为状态容器和基础设施，graph 节点通过 `_get_coder()` 访问 |
| `Commands` 类 | `commands.py` | 斜杠命令系统，独立于执行链 |
| `ToolExecutor` | `tools/executor.py` | 工具执行引擎，两条链共用 |
| `ToolCoordinator` | `tools/executor.py` | 工具分发 |
| `_init_tool_system()` | `base_coder.py` | 工具注册初始化 |
| `auto_commit()` | `base_coder.py` | Git 自动提交 |
| `_save_session()` | `base_coder.py` | 会话持久化 |
| `_process_legacy_edits()` | `base_coder.py` | 编辑格式兼容（wholefile/editblock），保留为 graph 的后处理步骤 |

## 3. 收口后的执行链

```
用户输入
  │
  ├─ 斜杠命令 → Commands.run() → 独立处理
  │
  └─ 对话消息 → Coder.run()
                 │
                 └─ AgentRuntime.run_user_turn()
                     │
                     └─ LangGraph graph.invoke()
                         │
                         ├─ prepare_context → route_mode
                         │   ├─ plan: plan_node → request_plan_approval → END
                         │   └─ act: model_node → route_after_model
                         │       ├─ tools: parse → permission → execute → observe → loop
                         │       └─ finish: summarize_node → END
```

## 4. 收口步骤（与里程碑任务对应）

### 步骤 1：收口命令执行入口（任务 3）

将 `/run` 和 `/git` 改为构造 `ToolCall("run_shell", ...)`，交给 `tool_executor.execute()`。

改动点：
- `commands.py` → `cmd_run()`: 构造 ToolCall → `self.coder.tool_executor.execute()`
- `commands.py` → `cmd_git()`: 同上
- 新增测试覆盖

### 步骤 2：统一权限入口（任务 4）

改动点：
- `permission_modes.py`：删除 `ACT_MODE_AUTO_APPROVED_COMMANDS` 中的危险命令
- 对齐 `permission_modes.py` 与 `approval.py` 的规则来源
- 新建权限矩阵文档

### 步骤 3：移除 Legacy 主循环（任务 5）

改动点：
- `Coder.run()`：删除环境变量判断，默认创建 `AgentRuntime` 并委托
- `_send_message_inner()`：降级为非公开方法，标记废弃
- `_process_tool_calls()`：同理
- 将 `_trim_context_for_model()` 的分层策略迁移到 `nodes._trim_messages()`
- 将 `summarize_if_needed()` 逻辑融入 `summarize_node()`
- 清理 debug stderr 写入

### 步骤 4：验证闭环（任务 6）

- pytest 全量通过
- CLI 单轮和 --serve 模式冒烟测试
- 更新文档

## 5. 当前状态（2026-05-09 更新）

- **步骤 1-3 已完成**：`/run` `/git` 走工具系统、权限收紧、`Coder.run()` 默认走 AgentRuntime
- **步骤 4 部分完成**：pytest 360 passed，CLI/RPC 冒烟待补
- `_send_message_inner()` 仍保留，`Coder.run()` 不再调用它（直接走 `_create_runtime`）
- `AICODER_LANGGRAPH_RUNTIME` 环境变量已从主代码移除（测试中有残留清理）
- 后续：完全移除 `_send_message_inner()` 和 `run_one()`，清理残留

## 6. 风险与取舍

| 风险 | 应对 |
|------|------|
| LangGraph checkpoint 需要额外依赖（sqlite） | 默认不启用 checkpoint，保持零配置可用 |
| `_process_legacy_edits()` 依赖 `self.partial_response_content` | 在 graph 流程中通过 state 传递，或保留为 graph 后处理 |
| RPC 模式（--serve）目前走 Coder.run() | 确保 AgentRuntime 路径对 RPC IO 兼容 |
| graph 的 interrupt 机制需要 LangGraph >= 0.2 | pyproject.toml 已声明 `langgraph>=0.2.0` |
