# LangGraph Interrupt Approval Integration — 设计文档

> Phase 4: Design only — no implementation.
> 本文档为阶段 6（审批与 interrupt 适配）提供完整技术设计。

---

## 1. 当前 ToolExecutor 审批链路（精确到行号）

### 1.1 两条并行审批路径

项目存在两条审批路径，共享决策逻辑但使用不同的阻塞机制：

```
路径 A: Graph path（legacy runtime 通过 LangGraph workflow）
  model_node → permission_node → execute_tool_node
  审批: graph/interrupts.py（interrupt 或 blocking IO）
  执行: execute_tool_node(skip_permission=True)

路径 B: Executor path（LangChain runtime 通过 _run_existing_tool）
  LangChain agent tool call → _run_existing_tool() → ToolExecutor.execute()
  审批: ToolExecutor._request_approval()（blocking IO）
  执行: 同一次 execute() 调用
```

### 1.2 ToolExecutor 内部决策链

`executor.py:_execute_inner()` 按以下顺序检查：

| 顺序 | 检查点 | 行号 | 说明 |
|------|--------|------|------|
| 1 | `did_reject_tool` | 114 | 之前有工具被拒绝，直接跳过 |
| 2 | handler lookup | 120 | 未知工具，直接失败 |
| 3 | write limits | 128 | 2MB / 10000 行限制 |
| 4 | validate_params | 133 | handler 参数校验 |
| 5 | `_get_permission_decision()` | 138-152 | 完整权限决策（见 1.3） |
| 6 | loop detection | 154 | 同参数重复 3 次 |
| 7 | `_execute_with_retry()` | 162 | 真正执行 |

### 1.3 权限决策链 `_get_permission_decision()`（行 341）

```
can_use_tool_in_mode()          ← 模式门控（sniff/plan/act）
  ↓ behavior != "ask"? → 直接返回 allow/deny
  ↓
handler.requires_approval       ← handler 门控
  ↓ False? → 跳过审批，返回 mode_result
  ↓
ApprovalController.should_auto_approve()  ← 自动审批
  ↓ True? → override 为 allow
  ↓
state.should_require_approval   ← 失败升级（3+ 连续失败强制 ask）
  ↓
最终行为: allow / ask / deny
```

### 1.4 交互审批 `_request_approval()`（行 371）

当决策为 `ask` 时：

```
IO 有 request_structured_approval()?
  YES → rpc_io.approval_request()
          → 发送 approval/request {id, question, diff}
          → _wait_response(approval_id)  ← Queue.get(timeout=300)
          → TUI 返回 approval/respond {id, approved}
          → 返回 bool(approved)
  NO  → confirm_ask()  ← 终端 fallback
```

### 1.5 拒绝传播机制

**两层保证，均不需要改动：**

1. **状态标记**：`_execute_inner()` 行 114 — `did_reject_tool=True` 后所有后续 `execute()` 直接返回失败
2. **批处理中断**：`execute_all()` 行 333-335 — `did_reject_tool` 后 break 循环
3. **LangChain 层**：`_run_existing_tool()` 检测 `result.success=False` → 抛出 `RuntimeError` → LangChain agent 收到工具错误 → 停止调用后续工具

---

## 2. 第一批受控工具

### 2.1 `requires_approval = True` 的工具

| 工具 | Handler | 行号 | 危险级别 |
|------|---------|------|----------|
| `write_file` | `WriteFileHandler` | `write_file_handler.py:20` | 高 — 覆写文件内容 |
| `edit_file` | `EditFileHandler` | `edit_file_handler.py:10` | 高 — 修改文件内容 |
| `run_shell` | `RunShellHandler` | `run_shell_handler.py:65` | 高 — 执行任意命令 |

### 2.2 `requires_approval = False` 的工具（不需要 interrupt）

| 工具 | Handler | 行号 | 说明 |
|------|---------|------|------|
| `read_file` | `ReadFileHandler` | `read_file_handler.py:16` | 只读 |
| `search_files` | `SearchFilesHandler` | `search_files_handler.py:12` | 只读 |
| `list_files` | `ListFilesHandler` | `list_files_handler.py:12` | 只读 |
| `list_code_defs` | `ListCodeDefsHandler` | `list_code_defs_handler.py:17` | 只读 |

### 2.3 为什么只有这三个

`ToolExecutor._get_permission_decision()` 在行 353-354 已经实现了分流：
- `handler.requires_approval = False` → 跳过交互审批，直接 allow
- `handler.requires_approval = True` → 进入交互审批链

interrupt 只需要关注 `requires_approval = True` 的工具。只读工具即使 mode 返回 `ask`，也会因为 handler 不需要审批而直接放行。

---

## 3. LangGraph interrupt / HITL 接入点

### 3.1 已有基础设施

项目已有完整的 interrupt 基础设施：

| 组件 | 位置 | 状态 |
|------|------|------|
| `interrupt()` | `langgraph.types` | 已安装可用 |
| `Command(resume=...)` | `langgraph.types` | 已安装可用 |
| `SqliteSaver` | `langgraph.checkpoint.sqlite` | 已安装可用 |
| 双模式切换 | `graph/interrupts.py` | 已实现 |
| checkpointer 工厂 | `graph/checkpointer.py` | 已实现 |
| permission_node | `graph/nodes.py:436` | 已实现 |

### 3.2 双模式切换机制

`graph/interrupts.py` 已实现：

```
AICODER_LANGGRAPH_CHECKPOINT=1?
  YES → langgraph.types.interrupt({...})
         图暂停 → 需要外部 Command(resume=True/False) 恢复
  NO  → _blocking_tool_approval()
         io.request_structured_approval() 或 io.confirm_ask()
         同步阻塞直到用户响应
```

### 3.3 LangChain runtime 接入点设计

**关键设计决策：LangChain runtime 不引入独立的 LangGraph interrupt 节点。**

原因：
1. LangChain `StructuredTool` 执行是同步的，在工具函数内部阻塞等待用户响应是自然的
2. `ToolExecutor._request_approval()` 已经实现了阻塞式审批
3. 引入 interrupt 需要 checkpointer + 状态恢复，复杂度远高于收益
4. 当前 LangChain runtime 只支持 `--message` 单轮模式

**接入方式：**

```
LangChain agent 产生 tool call
  → StructuredTool 函数执行
    → _run_existing_tool(coder, name, params)
      → coder.tool_executor.execute(ToolCall(...))
        → _execute_inner()
          → _get_permission_decision()  ← 权限决策
          → _request_approval()         ← 阻塞式审批
            → io.request_structured_approval()  (TUI/RPC)
            或 io.confirm_ask()                  (CLI)
          → 执行或拒绝
```

这是 **路径 B 的自然延伸**，不需要新增 interrupt 节点。

---

## 4. rpc_io.py approval/request 与 approval/respond 复用方案

### 4.1 现有协议

```
→  notification approval/request   {"id": uuid, "question": str, "diff": str|null}
←  notification approval/respond   {"id": uuid, "approved": bool}
```

### 4.2 两条路径如何使用同一个协议

| 路径 | 调用方 | 发送 | 等待 | 返回 |
|------|--------|------|------|------|
| Graph path | `permission_node` → `interrupts.py` → `io.request_structured_approval()` | `approval/request` | `Queue.get()` | `bool(approved)` |
| LangChain path | `ToolExecutor._request_approval()` → `io.request_structured_approval()` | `approval/request` | `Queue.get()` | `bool(approved)` |

**两条路径最终调用同一个 `io.request_structured_approval()` 方法**。TUI 不需要区分请求来自哪条路径。`approval_id`（UUID）确保了并发的请求-响应匹配。

### 4.3 不需要修改 rpc_io.py

当前 RPC 协议已经满足需求：
- `approval/request` 发送审批请求（含 diff 预览）
- `approval/respond` 返回用户决策
- UUID 关联确保无歧义

未来如需支持 **edit 模式**（用户修改工具参数后执行），可扩展 `approval/respond` 增加 `edited_params` 字段。但这不是本阶段范围。

---

## 5. 如何避免 ToolExecutor 审批和 LangGraph 审批双重弹窗

### 5.1 当前架构天然避免双重弹窗

```
                    ┌─ legacy runtime ────────────────────────┐
                    │  permission_node (图节点审批)             │
                    │    ↓ approved calls                      │
Coder.run() ────────┤  execute_tool_node(skip_permission=True) │
                    │    → ToolExecutor 不再审批               │
                    │                                          │
                    ├─ langchain runtime ──────────────────────┤
                    │  _run_existing_tool()                     │
                    │    → ToolExecutor.execute()               │
                    │      → _request_approval()  ← 唯一审批   │
                    └──────────────────────────────────────────┘
```

**Legacy runtime**：审批在 `permission_node` 完成，`execute_tool_node` 调用时传入 `skip_permission=True`，所以 `ToolExecutor` 不会二次审批。

**LangChain runtime**：`_run_existing_tool()` 调用 `ToolExecutor.execute()` 时不传 `skip_permission`（默认 `False`），所以 `ToolExecutor` 执行完整的审批链。

**关键保证：两条路径各自只经过一次审批。**

### 5.2 潜在的双重弹窗风险

如果未来在 LangChain runtime 中引入独立的 interrupt 审批节点（在 agent 和 tool 之间），而又不设 `skip_permission=True`，就会出现：
1. LangGraph interrupt 弹窗 → 用户批准
2. ToolExecutor._request_approval() 再弹窗 → 用户再次批准

**预防方案：**

如果引入 interrupt 审批节点，必须在调用 `ToolExecutor.execute()` 时传入 `skip_permission=True`，并记录已审批的工具列表。这遵循与 legacy runtime 的 `permission_node → execute_tool_node(skip_permission=True)` 相同的模式。

### 5.3 设计原则

> **审批只发生一次。** 如果审批在调用 ToolExecutor 之前已完成，必须传入 `skip_permission=True`。如果审批由 ToolExecutor 内部处理，不应在外部再添加审批节点。

---

## 6. Reject 后如何停止后续危险工具

### 6.1 三层保证（已实现，不需要改动）

```
Layer 1: ToolExecutor._execute_inner() 行 114
  if self._state.did_reject_tool:
      return ToolResult.fail("Skipped: previous tool was rejected")
  ↓ 一旦被标记，所有后续 execute() 直接失败

Layer 2: ToolExecutor.execute_all() 行 333-335
  if self._state.did_reject_tool:
      break  ← 跳过批量中剩余工具

Layer 3: LangChain StructuredTool → RuntimeError
  _run_existing_tool() 检测 result.success == False
    → raise RuntimeError(error_message)
    → handle_tool_errors middleware 转为 ToolMessage
    → LangChain agent 收到错误，不会继续调用同类工具
```

### 6.2 Reject 传播路径

```
用户点击拒绝
  → approval/respond {"approved": false}
  → rpc_io._handle_request() → Queue.put(False)
  → ToolExecutor._request_approval() 返回 False
  → state.did_reject_tool = True
  → 返回 ToolResult.create_rejected()
  → _run_existing_tool() 抛出 RuntimeError("User rejected the tool call.")
  → handle_tool_errors 转为 ToolMessage:
    "Tool error: User rejected. Reason: User rejected the tool call.
     Check the arguments, respect aiCoder safety policy, or choose a safer alternative."
  → LangChain agent 收到明确的拒绝信息
  → agent 决定下一步行动（通常停止或换安全方案）
  → 如果 agent 不顾错误继续调用同类工具
    → ToolExecutor._execute_inner() 行 114 立即拒绝
```

### 6.3 为什么不需要 LangGraph interrupt 来实现 reject 停止

当前 `_run_existing_tool()` + `ToolExecutor` 的同步阻塞模式已经完全覆盖了 reject 后的停止逻辑：

1. 每次工具调用都经过 `ToolExecutor`
2. `did_reject_tool` 标记在 `ExecutionState` 中，贯穿整个会话
3. `RuntimeError` 通过 `handle_tool_errors` 转为模型可理解的 `ToolMessage`

只有当需要 **跨进程中断恢复**（进程崩溃重启后继续）时，才需要 interrupt + checkpointer。

---

## 7. 为什么本阶段只设计不实现

### 7.1 设计验证优先

审批系统是安全边界。设计错误会导致：
- 双重弹窗 → 用户体验恶化
- 审批绕过 → 安全漏洞
- Reject 不停止 → 危险操作继续执行

先完成精确到行号的设计，确保每条路径都有覆盖。

### 7.2 依赖关系

Interrupt + checkpointer 接入（迁移计划阶段 6-7）依赖：
1. **LangChain runtime 交互模式** — 当前只支持 `--message` 单轮，interrupt 需要多轮交互
2. **session_id → thread_id 映射** — 需要 checkpointer 持久化
3. **TUI approval/respond 扩展** — 可能需要支持 `edit` 模式（用户修改参数后执行）
4. **有副作用工具的幂等性** — 恢复时避免重复执行

这些依赖项尚未就绪，实现会引入不完整功能。

### 7.3 当前状态已足够安全

LangChain runtime 的审批已通过 `ToolExecutor` 内部链路完整覆盖：
- `_get_permission_decision()` → 模式门控 + 自动审批 + 失败升级
- `_request_approval()` → RPC 阻塞式审批 或 终端 confirm
- `did_reject_tool` → 拒绝传播
- `handle_tool_errors` → 错误转为 ToolMessage

不需要 interrupt 也能安全运行。

### 7.4 实现阶段预览

当以下条件满足时，可以进入实现：

| 前置条件 | 当前状态 |
|----------|----------|
| LangChain runtime 支持交互模式 | 未实现 |
| session_id → thread_id 映射 | `graph/checkpointer.py` 已有 `get_thread_config()` |
| checkpointer 接入 | `SqliteSaver` 已安装，`create_react_agent` 支持 `checkpointer` 参数 |
| interrupt 恢复逻辑 | `agent_app_runner.py` 已有 `_has_pending_interrupt()` 模式 |
| 避免双重弹窗 | 本文档已设计保证方案 |

实现时的代码变更预计：
1. `agent.py`：传入 `checkpointer` 和 `config`
2. `tools.py`：对受控工具传入 `skip_permission=True`，改用外部 interrupt 审批
3. `rpc_io.py`：**不改**（除非需要 edit 模式）
4. 新增 `langchain_runtime/approval.py`：interrupt 审批适配层

---

## 附录：关键文件行号索引

| 文件 | 函数/逻辑 | 行号 |
|------|-----------|------|
| `executor.py` | `execute()` | 102 |
| `executor.py` | `_execute_inner()` — reject guard | 114 |
| `executor.py` | `_execute_inner()` — permission gate | 138-152 |
| `executor.py` | `_get_permission_decision()` | 341 |
| `executor.py` | `_request_approval()` | 371 |
| `executor.py` | `execute_all()` — break on reject | 333-335 |
| `approval.py` | `should_auto_approve()` | 153 |
| `approval.py` | `TOOL_CATEGORY_MAP` | 75 |
| `permission_modes.py` | `can_use_tool_in_mode()` | 58 |
| `rpc_io.py` | `approval_request()` | 249 |
| `rpc_io.py` | `request_structured_approval()` | 260 |
| `rpc_io.py` | `_wait_response()` | 197 |
| `rpc_io.py` | `_handle_request()` — approval/respond | 111-119 |
| `interrupts.py` | `request_tool_approval()` | 28 |
| `interrupts.py` | `_has_checkpointer()` | 17 |
| `interrupts.py` | `_blocking_tool_approval()` | 105 |
| `nodes.py` | `permission_node()` | 436 |
| `nodes.py` | `execute_tool_node()` — skip_permission=True | 594 |
| `checkpointer.py` | `get_checkpointer()` | 12 |
| `checkpointer.py` | `get_thread_config()` | 34 |
| `tools.py` | `_run_existing_tool()` | 21 |
| `middleware.py` | `format_tool_error_message()` | 全文件 |
