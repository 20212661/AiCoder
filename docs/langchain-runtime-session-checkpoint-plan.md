# LangChain Runtime Session & Checkpoint 设计文档

> Phase 4: Design only — no implementation.
> 本文档回答 session_id、thread_id、checkpointer、副作用恢复等关键设计问题。

---

## 1. 当前 aiCoder session 保存/恢复链路

### 1.1 存储

| 路径 | 内容 |
|------|------|
| `~/.aicoder/sessions/index.json` | 全局索引，按 `updated_at` 降序 |
| `~/.aicoder/sessions/<id>/session_meta.json` | 元数据：session_id, model_name, token_in/out, first_message, root |
| `~/.aicoder/sessions/<id>/api_conversation_history.json` | `{"done_messages": [...], "cur_messages": [...]}` |

序列化方式：JSON（`json.dump`，indent=2，UTF-8）。

### 1.2 保存时机

`coder._save_session()` 在以下位置被调用：

| 调用点 | 文件:行号 | 触发条件 |
|--------|-----------|----------|
| `summarize_node()` | `nodes.py:1068` | 每个 graph turn 结束时 |
| `request_plan_approval()` | `nodes.py:229` | plan-only 模式完成时 |
| `_finalize_on_error()` | `agent_runtime.py:52` | 异常路径 |
| `cmd_save()` | `commands.py:406` | 用户手动 `/save` |

### 1.3 保存内容

```python
save_session(
    session_id,
    done_messages,   # coder.done_messages — 已完成对话轮次
    cur_messages,    # coder.cur_messages — 当前轮次消息
    SessionMeta(     # 元数据
        session_id, model_name, edit_format,
        token_in, token_out, first_message, root,
        created_at=time.time(), updated_at=time.time()
    )
)
```

### 1.4 恢复流程

```
main.py:318-322   --resume <id> → load_session(id) → (meta, done, cur)
main.py:354-359   → coder.done_messages = done
                   → coder.cur_messages = cur
                   → coder.session_id = meta.session_id
                   → coder._first_user_message = meta.first_message
```

### 1.5 LangChain runtime 当前状态

**完全无 session 持久化。** `run_langchain_agent()` 是无状态单轮调用：
- 不调用 `coder._save_session()`
- 不写入 `done_messages` / `cur_messages`
- 不使用 `coder.session_id`
- 每次调用独立，结束后不留痕迹

---

## 2. coder.session_id 从哪里来，什么时候为空

### 2.1 来源

| 场景 | 来源 | 代码位置 |
|------|------|----------|
| 正常启动 | `new_session_id()` → `uuid.uuid4().hex[:12]` | `main.py:323` |
| 恢复会话 | `meta.session_id`（从 JSON 文件读取） | `main.py:358` |
| `--no-save` | `None`（不创建 session_id） | `main.py:323` 条件跳过 |

### 2.2 何时为空

| 条件 | session_id 值 | 影响 |
|------|---------------|------|
| `--no-save` 参数 | `None` | `_save_session()` 行 340 直接返回，不写入 |
| `--serve` 模式（新连接） | 取决于 TUI 是否传入 session | `rpc_io.py` 可创建新 session |
| LangChain runtime 当前 | 由 `main.py` 设置，但 agent 不使用 | `run_langchain_agent()` 忽略它 |

### 2.3 LangChain runtime 中的可用性

即使 session_id 在 `main.py` 中已设置到 `coder.session_id`，当前 LangChain runtime 完全不读取它。如果未来需要 session 持久化，`coder.session_id` 已经可用，不需要新建字段。

---

## 3. LangGraph thread_id 如何映射 coder.session_id

### 3.1 现有映射机制

`graph/checkpointer.py:34-40` 已实现：

```python
def get_thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
```

**直接映射：`coder.session_id` 就是 `thread_id`。**

### 3.2 为什么直接映射可行

- `coder.session_id` 是 12 字符 hex（`uuid.uuid4().hex[:12]`），全局唯一
- LangGraph `thread_id` 只需要是字符串标识符
- 不需要转换或额外命名空间

### 3.3 使用方式

```python
# agent 构建时
checkpointer = get_checkpointer()  # SqliteSaver
agent = create_react_agent(model, tools, checkpointer=checkpointer)

# 调用时
config = get_thread_config(coder.session_id)
result = agent.invoke({"messages": [...]}, config=config)
```

### 3.4 session_id 为空时的处理

当 `coder.session_id is None`（`--no-save` 模式），不应该启用 checkpointer。因为：
- checkpointer 需要持久化标识符
- `--no-save` 的语义是"不留痕迹"
- 使用 `None` 作为 thread_id 会导致所有无 session 调用共享同一个检查点

---

## 4. --runtime langchain --message 是否应该写入现有 session

### 4.1 建议：应该写入

理由：
1. **用户预期**：用户使用 `--runtime langchain --message "fix bug"` 期望对话被记录，和 legacy runtime 行为一致
2. **调试需要**：session 历史是唯一的回溯手段
3. **session_id 已存在**：`coder.session_id` 在 `main.py` 中已设置，不需要额外逻辑

### 4.2 需要写入的内容

```
done_messages:
  - {"role": "user", "content": user_message}
  - {"role": "assistant", "content": response_text}
  - （工具调用记录，如果需要）
```

### 4.3 写入时机

```python
# base_coder.py run() 的 langchain 分支中
text = run_langchain_agent(self, with_message)

# 写入 session（需要新增）
self.cur_messages.append({"role": "user", "content": with_message})
self.cur_messages.append({"role": "assistant", "content": text})
self.done_messages.extend(self.cur_messages)
self.cur_messages = []
self._save_session()
```

### 4.4 例外

`--no-save` 时不写入 — `coder.session_id` 为 `None`，`_save_session()` 行 340 直接返回。

---

## 5. structured_response 是否应该进入 session history

### 5.1 建议：不直接存储原始 structured_response

理由：
1. **session history 的消费者是人**（用户通过 `--resume` 或 `--list-sessions` 查看）
2. `AICoderResponse` 的结构化字段（`changed_files`, `commands_run`）适合 TUI 展示，不适合纯文本 history
3. `summary` 已经是面向人的文本摘要

### 5.2 建议存储格式

```python
# session history 中存储
{"role": "assistant", "content": summary_text}

# 不存储
{"role": "assistant", "structured_response": {...}}  # 不推荐
```

### 5.3 结构化数据去哪

结构化数据适合通过 checkpointer 存储（LangGraph state 包含完整消息历史和 structured_response），而非 JSON session 文件。两层存储各司其职：

| 存储 | 存什么 | 消费者 |
|------|--------|--------|
| JSON session | summary 文本 | 用户回溯、`--resume` |
| SQLite checkpointer | 完整消息 + structured_response | LangGraph interrupt/resume |

---

## 6. ToolResult / ToolMessage 如何进入历史

### 6.1 Legacy runtime 的做法

```
nodes.py 中各节点：
  coder.cur_messages.append({"role": "user", "content": "[tool_name] Result:\n..."})
  或
  coder.cur_messages.append({"role": "user", "content": "[tool_name] FAILED:\n..."})
```

`ToolResult.to_message()` 将结果转为 `{role: "user", content: "[tool_name] ..."}` 格式。

### 6.2 LangChain runtime 当前做法

**不写入任何历史。** `_run_existing_tool()` 返回字符串或抛出 `RuntimeError`，`handle_tool_errors` middleware 将异常转为 `ToolMessage`，但这些只存在于 LangChain agent 的内部消息流中，不会写入 `coder.done_messages`。

### 6.3 建议：仅在 session history 中记录摘要

不需要将每个工具调用细节写入 session history。建议只记录：

```python
# 用户的输入
{"role": "user", "content": with_message}

# 最终响应（可能包含工具调用摘要）
{"role": "assistant", "content": response_summary}
```

工具调用的完整记录由 LangGraph checkpointer 或 LangChain agent 内部消息流保存。Session history 保持面向人的简洁格式。

### 6.4 如果需要详细工具日志

未来可通过 `ExecutionState` 或自定义 logger 记录工具调用明细到独立文件（如 `~/.aicoder/sessions/<id>/tool_trace.jsonl`），但这是独立的调试功能，不属于 session history。

---

## 7. checkpointer 用 sqlite 放在哪里

### 7.1 现有位置

```
~/.aicoder/langgraph/checkpoints.sqlite
```

定义在 `graph/checkpointer.py:8-9`。

### 7.2 为什么和 session 分开存放

| 文件 | 位置 | 格式 | 生命周期 |
|------|------|------|----------|
| session JSON | `~/.aicoder/sessions/<id>/` | JSON | 用户可见，可手动删除 |
| checkpointer DB | `~/.aicoder/langgraph/checkpoints.sqlite` | SQLite | 内部状态，按 thread_id 管理 |

分开存放的原因：
1. session JSON 是用户可见的对话历史，可以手动编辑
2. checkpointer DB 是 LangGraph 内部序列化状态，不应手动修改
3. 清理策略不同：session 可按目录删除，checkpointer 需要按 thread_id 清理

### 7.3 LangChain runtime 的 checkpointer

LangChain runtime 使用同一个 `SqliteSaver` 实例和同一个数据库。通过 `thread_id`（= `coder.session_id`）区分不同会话的检查点。

### 7.4 不使用内存 checkpointer

`InMemorySaver` 不持久化到磁盘，进程重启后丢失。只适合测试。生产环境必须用 `SqliteSaver`。

---

## 8. 哪些工具有副作用，恢复时如何避免重复执行

### 8.1 副作用分类

| 工具 | 副作用 | `had_file_edits` 追踪 | 幂等性 |
|------|--------|----------------------|--------|
| `read_file` | 无 | 否 | **幂等** |
| `search_files` | 无 | 否 | **幂等** |
| `list_files` | 无 | 否 | **幂等** |
| `list_code_defs` | 无 | 否 | **幂等** |
| `write_file` | 创建/覆写文件 | **是** | **不幂等** — 重放覆盖变更 |
| `edit_file` | 修改文件内容 | **是** | **不幂等** — SEARCH 块已不存在 |
| `run_shell` | 依赖命令 | **否**（gap） | **不幂等** — 几乎无幂等 shell 命令 |

### 8.2 当前追踪机制

`ExecutionState.had_file_edits`（`result.py:119`）只追踪 `write_file` 和 `edit_file`。

**缺口：** `run_shell` 可以修改文件系统（`git commit`、`rm`、`mkdir`、`pip install`），但不设置 `had_file_edits`。Shell 引起的文件变更不会被自动 commit 或追踪。

### 8.3 恢复时的重复执行问题

当 checkpointer 恢复一个被 interrupt 的会话时，LangGraph 会重新执行被中断的节点。如果节点内有副作用工具调用，这些调用可能重复执行。

### 8.4 防止重复执行的策略

**策略 A：已执行工具记录（推荐）**

在 agent state 中维护 `executed_tool_calls: dict[str, ToolResult]`，key 为 `(tool_name, params_hash)`。

```python
# 恢复时检查
if (tool_name, params_hash) in executed_tool_calls:
    return executed_tool_calls[(tool_name, params_hash)]
```

优点：精确，不依赖命令幂等性。
缺点：需要额外状态管理。

**策略 B：工具执行幂等性标记**

为每个工具定义 `is_idempotent: bool`。恢复时只重放幂等工具，非幂等工具需要用户确认。

**策略 C：一次性工具票据**

每个工具调用分配唯一票据（UUID），执行后票据失效。恢复时检查票据是否已使用。

### 8.5 推荐方案

**本阶段不实现。** 当进入 checkpointer 实现阶段时：

1. 优先使用 **策略 A**（已执行工具记录）
2. `run_shell` 必须作为非幂等工具处理
3. 恢复后首次副作用工具调用必须经过用户确认

---

## 9. 何时才适合实现 checkpointer

### 9.1 前置条件检查清单

| 前置条件 | 当前状态 | 说明 |
|----------|----------|------|
| LangChain runtime 交互模式 | 未实现 | 当前只支持 `--message` 单轮 |
| session 写入 LangChain runtime | 未实现 | `run_langchain_agent()` 不写 session |
| interrupt 审批机制 | 已设计（Phase 4 上一阶段） | 但未实现 |
| structured_response 稳定 | 已实现 | `AICoderResponse` 已接入 |
| `create_react_agent` 支持 checkpointer | **已支持** | 签名中有 `checkpointer` 参数 |
| `SqliteSaver` 可用 | **已安装** | `langgraph-checkpoint-sqlite>=2.0.0` |
| session_id → thread_id 映射 | **已实现** | `get_thread_config()` |
| 副作用工具幂等性方案 | 未设计详细方案 | 需要策略 A 的详细设计 |

### 9.2 实现优先级排序

```
Step 1: LangChain runtime 写入 session history（低成本，高价值）
Step 2: LangChain runtime 交互模式（前置条件）
Step 3: interrupt 审批机制实现（依赖 Step 2）
Step 4: checkpointer 接入（依赖 Step 1-3）
Step 5: 副作用工具防重放（依赖 Step 4）
```

### 9.3 什么时候可以接 checkpointer

当 Step 1-3 完成后。预计在迁移计划阶段 7。

---

## 10. 为什么本阶段只设计不实现

### 10.1 依赖链未就绪

```
checkpointer 需要 interrupt（用于暂停/恢复）
interrupt 需要交互模式（用于等待用户响应）
交互模式需要 session 写入（用于记录对话）
```

当前 LangChain runtime 是无状态单轮模式，checkpointer 没有意义——没有需要恢复的状态。

### 10.2 副作用恢复是安全关键

如果恢复时重复执行 `write_file`、`edit_file` 或 `run_shell`，可能导致：
- 文件被覆盖为旧版本
- git commit 重复
- 包被重复安装
- 数据被删除

在副作用防重放方案设计完成之前，接入 checkpointer 是危险的。

### 10.3 当前状态已满足基本需求

- `--runtime langchain --message` 可以正常工作
- 工具审批通过 `ToolExecutor` 内部链路完成
- 工具错误通过 `handle_tool_errors` middleware 处理
- 用户可以通过 `--runtime legacy` 使用完整的 session 功能

LangChain runtime 的 session 写入（Step 1）是独立于 checkpointer 的，可以先实现，不需要等 checkpointer。

### 10.4 设计验证

本阶段的设计输出：
1. 明确了 session_id → thread_id 的直接映射关系
2. 明确了 LangChain runtime 应该写入 session history
3. 明确了 structured_response 不进 session，只进 checkpointer
4. 明确了副作用工具分类和防重放策略方向
5. 明确了实现优先级和前置条件

这些设计决策需要在实现前得到验证和确认。

---

## 附录：关键数据流对比

### Legacy runtime（有完整 session + checkpointer）

```
main.py: new_session_id() or load_session()
  ↓
Coder.__init__: session_id, done_messages, cur_messages
  ↓
agent_runtime.py: register_coder(session_id, coder)
  ↓
graph nodes: mutate coder.done_messages / cur_messages
  ↓
summarize_node: coder._save_session() → JSON files
  ↓
checkpointer: graph state → SQLite (optional, AICODER_LANGGRAPH_CHECKPOINT=1)
```

### LangChain runtime（当前：无 session）

```
main.py: new_session_id()
  ↓
Coder.__init__: session_id (set but unused)
  ↓
base_coder.py run(): langchain branch → run_langchain_agent()
  ↓
agent.py: stateless invoke, no session write
  ↓
(no session save, no checkpointer)
```

### LangChain runtime（未来：有 session + checkpointer）

```
main.py: new_session_id()
  ↓
Coder.__init__: session_id
  ↓
base_coder.py run(): langchain branch
  ↓
agent.py:
  - append to coder.cur_messages
  - invoke with config = get_thread_config(coder.session_id)
  - extract response → append to cur_messages
  - move to done_messages
  - coder._save_session()
  ↓
checkpointer: agent state → SQLite (always on for langchain runtime)
```

## 附录：文件行号索引

| 文件 | 函数/逻辑 | 行号 |
|------|-----------|------|
| `session.py` | `SessionMeta` dataclass | 26-44 |
| `session.py` | `save_session()` | 114 |
| `session.py` | `load_session()` | 134 |
| `session.py` | `new_session_id()` | 149 |
| `main.py` | session_id 创建/恢复 | 316-362 |
| `base_coder.py` | `session_id` 字段 | 38 |
| `base_coder.py` | `_save_session()` | 338-358 |
| `graph/state.py` | `AgentGraphState` | 65-90 |
| `graph/state.py` | `_coder_registry` | 49-62 |
| `graph/nodes.py` | `_get_coder()` | 15-22 |
| `graph/nodes.py` | `_save_session()` 调用 | 229, 1068 |
| `graph/checkpointer.py` | `get_checkpointer()` | 12 |
| `graph/checkpointer.py` | `get_thread_config()` | 34 |
| `agent_runtime.py` | `_create_runtime()` | 55 |
| `agent_runtime.py` | `run_user_turn()` | 22 |
| `agent_app_runner.py` | session 绑定 | 34, 61, 84 |
| `langchain_runtime/agent.py` | `run_langchain_agent()` | 95-100 |
| `tools/result.py` | `ExecutionState.had_file_edits` | 119 |
| `executor.py` | `had_file_edits` 设置 | 224-225 |
| `modes/config.py` | `FILE_EDIT_TOOLS` | 54 |
