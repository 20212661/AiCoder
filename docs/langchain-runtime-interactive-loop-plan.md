# LangChain Runtime Interactive Loop — 设计文档

> Phase 7: Design only — no implementation.
> 本文档为 LangChain runtime 的交互模式提供完整技术设计。

---

## 1. 当前 legacy interactive loop 在哪里，如何读取用户输入

### 1.1 三层循环架构

```
Layer 1: Outer Process Loop         main.py:386-406
  while True:                       一个 Coder 生命周期
    result = coder.run()            一轮用户对话
    if SwitchCoder: rebuild Coder   模型/格式切换时重建

Layer 2: Interactive Session Loop   base_coder.py:329-337
  while True:                       每轮 = 读取输入 + 执行
    um = self.get_input()           从 CLI 或 RPC 读取
    runtime = _create_runtime(self)
    runtime.run_user_turn(um)       单轮执行，返回值丢弃
  KeyboardInterrupt → double-Ctrl-C 退出
  SwitchCoder → 返回给 Layer 1
  EOFError → return None → Layer 1 break

Layer 3: Agentic Turn Loop          LangGraph graph 内部
  model → parse → permission → execute → observe → model
  max_loops=5，由 route_after_observe 控制
```

### 1.2 输入读取路径

**CLI 模式：** `base_coder.get_input()` → `io.get_input()` → `InputOutput.get_input()`（`io.py:53-71`）
- 优先使用 `prompt_toolkit`（带历史记录）
- Fallback 到 `input()`
- `EOFError` 向上传播

**TUI/RPC 模式：** `rpc_io.serve()` 有自己的 `while self._running` 循环（`rpc_io.py:313-363`）
- 不经过 `base_coder.run()` 的 Layer 2 循环
- 每次迭代：`get_input()` 发送 `input/request` → 阻塞等 `input/submit` → `coder.run(with_message=user_input)` 一次性执行
- 命令处理内联在 serve() 中

### 1.3 关键发现：两个独立的交互循环

| 模式 | 循环位置 | 每轮执行 |
|------|----------|----------|
| CLI | `base_coder.py:329-337` | `coder.run()` 无参数 → 内部 `get_input()` + `run_user_turn()` |
| TUI | `rpc_io.py:313-363` | `serve()` 自身循环 → `coder.run(with_message=...)` 一次性 |

这意味着交互模式不能只在 `base_coder.run()` 中实现——必须同时在两个位置处理。

---

## 2. --runtime langchain 交互模式应该挂在哪一层

### 2.1 设计决策：挂在 Layer 2（与 legacy 相同的位置）

**原因：**

1. Layer 2 已经处理 `get_input()`、slash commands、KeyboardInterrupt、SwitchCoder
2. Layer 1 不需要改动——它只负责 Coder 重建
3. Layer 3 在 LangChain runtime 中由 `create_react_agent` 内部管理，不需要额外循环

### 2.2 具体位置

**CLI 模式：** `base_coder.py:run()` 中 langchain 分支，当前返回 None 当 `with_message is None`。改为进入 while-True 循环：

```python
if getattr(self, "runtime", "legacy") == "langchain":
    if with_message:
        # 现有逻辑：一次性执行 + session 保存
        ...
        return text
    # 新增：交互循环
    while True:
        try:
            um = self.get_input()
            if not um: continue
            text = run_langchain_agent(self, um)
            self.io.print_assistant_output(text)
            # session 保存（与一次性模式相同）
            if self.session_id:
                self.cur_messages.append(dict(role="user", content=um))
                if not self._first_user_message:
                    self._first_user_message = um
                self.cur_messages.append(dict(role="assistant", content=text or ""))
                self.done_messages.extend(self.cur_messages)
                self.cur_messages = []
                self._save_session()
        except KeyboardInterrupt:
            self.keyboard_interrupt()
        except SwitchCoder as s:
            return s
```

**TUI 模式：** `rpc_io.serve()` 已有独立循环，调用 `coder.run(with_message=user_input)`。当前 langchain 分支已正确处理 `with_message`。**TUI 模式不需要改动。**

### 2.3 为什么不在 rpc_io 层面改动

`rpc_io.serve()` 的循环已经在每次收到用户输入时调用 `coder.run(with_message=user_input)`。这对 langchain runtime 已经正确工作——它走的是 `with_message` 一次性路径。不需要修改 `rpc_io.py`。

---

## 3. CLI interactive 和 TUI --serve 是否同阶段支持

### 3.1 结论：分阶段

| 阶段 | 支持的模式 | 工作量 |
|------|-----------|--------|
| 阶段 7a | CLI interactive | 修改 `base_coder.py` 的 langchain 分支 |
| 阶段 7b | TUI `--serve` | 已天然支持——`serve()` 循环 + `coder.run(with_message=...)` |

### 3.2 为什么 TUI 已经支持

`rpc_io.serve()` 的流程：

```
TUI 发送 input/submit {"content": "user message"}
  → serve() 循环调用 coder.run(with_message="user message")
    → langchain 分支：run_langchain_agent() + session 保存
  → 返回 text
  → serve() 发送 status/update {"phase": "idle"}
```

这条路径已经在 Phase 6 中完成了 session 保存。TUI 用户可以用 `--runtime langchain --serve` 进行多轮对话。

### 3.3 阶段 7a 的额外工作

只需让 CLI 的 `coder.run()`（无参数）进入 langchain 交互循环。核心修改量：`base_coder.py` 的 langchain 分支，约 15 行代码。

---

## 4. 每一轮如何调用 run_langchain_agent()

### 4.1 与一次性模式完全一致

每轮交互的执行逻辑与 `--message` 一次性模式相同：

```python
from ..langchain_runtime.agent import run_langchain_agent
text = run_langchain_agent(self, user_message)
```

每次调用都会：
1. `build_langchain_agent(coder)` — 构建 agent（含 tools、middleware、response_format）
2. `agent.invoke({"messages": [...]})` — 执行（内部有自己的工具循环）
3. `extract_langchain_response_text(result)` — 提取响应

### 4.2 是否需要跨轮保持 agent 实例

**当前设计：不需要。** 每轮重新构建 agent。原因：
1. `create_react_agent` 没有内置的跨轮消息历史——每次 invoke 是独立的
2. 跨轮历史通过 `coder.done_messages` 管理（与 legacy runtime 相同）
3. 构建 agent 的成本很低（不包含模型调用）

### 4.3 未来优化

如果性能敏感，可以缓存 agent 实例。但这需要处理工具函数闭包中 `coder` 引用的生命周期问题。当前阶段不值得引入。

---

## 5. 每一轮如何保存 session

### 5.1 与 Phase 6 一次性模式完全一致

```python
if self.session_id:
    self.cur_messages.append(dict(role="user", content=um))
    if not self._first_user_message:
        self._first_user_message = um
    self.cur_messages.append(dict(role="assistant", content=text or ""))
    self.done_messages.extend(self.cur_messages)
    self.cur_messages = []
    self._save_session()
```

### 5.2 与 legacy runtime 的一致性

| 行为 | Legacy runtime | LangChain runtime |
|------|---------------|-------------------|
| 保存时机 | `summarize_node()` 每轮结束 | 每轮 `run_langchain_agent()` 返回后 |
| 保存内容 | `{role: user/assistant}` 消息 | 相同 |
| `cur_messages` 处理 | extend 到 done_messages 后清空 | 相同 |
| `session_id` 为空 | `_save_session()` 直接返回 | 相同 |

---

## 6. 工具审批阻塞时如何复用现有 IO

### 6.1 LangChain runtime 的审批路径

```
LangChain agent 产生 tool call
  → StructuredTool 函数执行
    → _run_existing_tool(coder, name, params)
      → coder.tool_executor.execute(ToolCall(...))
        → _execute_inner()
          → _get_permission_decision()
          → _request_approval()              ← 阻塞点
            → io.request_structured_approval() (TUI/RPC)
            或 io.confirm_ask()                (CLI)
```

### 6.2 CLI 模式下的阻塞

`io.confirm_ask()` 使用 `prompt_toolkit` 或 `input()` 同步读取用户确认。LangChain agent 的工具执行线程阻塞，等待用户响应。

这与 legacy runtime 的行为一致——legacy runtime 的 `permission_node` 通过 `_blocking_tool_approval()` 同样阻塞在 `io.confirm_ask()`。

### 6.3 TUI 模式下的阻塞

`io.request_structured_approval()` 发送 `approval/request` 到 TUI，阻塞在 `Queue.get(timeout=300)`。TUI 返回 `approval/respond` 后解除阻塞。

### 6.4 不需要额外处理

当前架构中，工具审批的阻塞发生在 `ToolExecutor._request_approval()` 内部。LangChain runtime 的 `_run_existing_tool()` 已经通过 `coder.tool_executor.execute()` 走这条路径。**不需要修改任何 IO 层代码。**

---

## 7. 是否支持 streaming，若不支持如何降级

### 7.1 当前状态

`run_langchain_agent()` 使用 `agent.invoke()` — 完全同步，无 streaming。

### 7.2 LangChain streaming API

`create_react_agent` 支持 `agent.stream()` 和 `agent.astream()`，可以逐 token 输出。

### 7.3 建议：本阶段不支持 streaming

原因：
1. streaming 需要改变 `run_langchain_agent()` 的返回类型（从 `str` 变为 generator/stream）
2. CLI 交互模式需要逐 token print，与当前的 `print_assistant_output(text)` 一次性输出不兼容
3. `extract_langchain_response_text()` 的 structured_response 解析需要完整结果
4. 工具执行过程中的中间状态展示需要额外处理

### 7.4 降级策略

- `build_chat_model()` 已设置 `temperature=0`
- `agent.invoke()` 同步执行，用户在等待期间看到工具执行的 IO 输出（由 ToolExecutor 的 `_emit_mode_reason` 和 `tool_call_started/finished` 产生）
- 响应完成后一次性显示

### 7.5 未来 streaming 实现路径

```
agent.stream({"messages": [...]})
  → 逐 token 产出 AIMessageChunk
  → io.print_streaming(token)
  → 工具执行时暂停 streaming，显示工具结果
  → 最终响应完成后，extract_langchain_response_text() 处理完整结果
```

这是独立优化项，不影响交互循环设计。

---

## 8. 用户输入 /quit、/clear、/resume、/model 等命令如何处理

### 8.1 命令路由路径

`base_coder.get_input()` 已经处理 slash commands：

```python
def get_input(self):
    ui = self.io.get_input(...)
    if ui and self.commands and self.commands.is_command(ui):
        r = self.commands.run(ui)
        if isinstance(r, str): return r    # 合成用户输入
        return None                         # 命令已处理，跳过本轮
    return ui
```

LangChain 交互循环调用 `self.get_input()`，天然继承所有 slash commands。

### 8.2 各命令在 LangChain runtime 中的行为

| 命令 | 行为 | 影响 |
|------|------|------|
| `/model <name>` | 触发 `SwitchCoder` | 返回给 Layer 1 重建 Coder。新建的 Coder 继承 `runtime="langchain"` |
| `/clear` | 清空 `done_messages` 和 `cur_messages` | 继续循环。LangChain runtime 下一轮看不到之前的历史 |
| `/resume <id>` | 加载 session 到 coder 消息数组 | 继续循环。LangChain runtime 下一轮的 `done_messages` 包含恢复的历史 |
| `/act`、`/plan`、`/sniff` | 修改 `tool_exec_state.mode` | 影响下一轮 `ToolExecutor` 的权限决策 |
| `/yolo` | 切换自动审批 | 影响下一轮 `ToolExecutor` 的审批行为 |
| `/add`、`/drop` | 修改 `coder.abs_fnames` | 影响工具执行时的文件访问 |
| `/help` | 打印帮助 | 继续循环 |
| `/save` | 手动保存 session | 继续循环 |
| `/commit` | 手动 git commit | 继续循环 |
| `/diff` | 显示 diff | 继续循环 |
| `/quit` | 不存在为命令方法 | CLI 通过 EOF（Ctrl-D）退出；TUI 通过 `rpc_io` 的 `/quit` break |

### 8.3 `/model` 的 SwitchCoder 流程

```
用户输入 /model deepseek-chat
  → commands.run("/model deepseek-chat")
  → SwitchCoder(main_model=Model("deepseek-chat"), edit_format="whole")
  → base_coder.run() 捕获 SwitchCoder，return s
  → main.py Layer 1 捕获
  → coder = Coder.create(**kwargs)
  → coder.runtime = args.runtime  ← 新 Coder 继承 runtime="langchain"
  → continue 回到 Layer 1 循环
```

**关键点：** `main.py:389` 的 SwitchCoder 处理已经会重建 Coder。新 Coder 的 `runtime` 属性由 `main.py` 的 `coder.runtime = args.runtime` 设置（行 373）。所以 `/model` 切换后 langchain runtime 会继续生效。

### 8.4 `/clear` 的特殊处理

`/clear` 清空 `done_messages`。LangChain runtime 每轮独立调用 `run_langchain_agent()`，不依赖 `done_messages` 作为上下文。所以 `/clear` 只影响 session 存储，不影响 LangChain agent 的行为。

如果未来需要将 `done_messages` 传入 LangChain agent 作为上下文，`/clear` 会同时清空上下文。这是正确的行为。

---

## 9. run_langchain_agent 异常时如何展示和恢复下一轮

### 9.1 异常类型

| 异常 | 来源 | 恢复策略 |
|------|------|----------|
| `RuntimeError` | 工具执行失败（`_run_existing_tool`） | 已由 `handle_tool_errors` middleware 捕获，转为 ToolMessage。agent 继续运行 |
| LLM API error | `ChatLiteLLM` 调用失败 | 未被 middleware 捕获，冒泡到 `run_langchain_agent()` |
| `KeyboardInterrupt` | 用户 Ctrl-C | 中断当前轮，进入 `keyboard_interrupt()` 处理 |
| 其他 Exception | LangChain 内部错误 | 冒泡到交互循环 |

### 9.2 设计：try/except 包裹每轮

```python
while True:
    try:
        um = self.get_input()
        if not um: continue
        text = run_langchain_agent(self, um)
        self.io.print_assistant_output(text)
        # session 保存...
    except KeyboardInterrupt:
        self.keyboard_interrupt()
    except SwitchCoder as s:
        return s
    except Exception as e:
        self.io.tool_error(f"LangChain runtime error: {e}")
        # 不保存 assistant 消息（与 Phase 6 一致）
        continue  # 恢复下一轮
```

### 9.3 与 legacy runtime 的一致性

Legacy runtime 的异常处理：

| 异常 | Legacy 处理 | LangChain 处理 |
|------|------------|----------------|
| `LLMError` | `agent_runtime.py:32-38` 捕获，打印错误，`_finalize_on_error()` | 通用 Exception 捕获，打印错误，continue |
| `KeyboardInterrupt` | `base_coder.py:336` → `keyboard_interrupt()` | 相同 |
| `SwitchCoder` | `base_coder.py:337` → return | 相同 |
| `EOFError` | `base_coder.py:338` → return None | 相同 |

### 9.4 错误后的 session 状态

异常时不保存 assistant 消息（与 Phase 6 设计一致）。用户输入可能已经在 `cur_messages` 中（取决于异常发生的时机），但因为 `cur_messages` 在下一轮开始前不会被 extend 到 `done_messages`，所以不会污染持久化的历史。

---

## 10. 为什么本阶段只设计不实现

### 10.1 实现量极小但影响面需要验证

交互循环的修改量约 15 行代码（`base_coder.py` langchain 分支的 else 块）。但需要验证：

1. SwitchCoder 在 langchain runtime 中的行为（新 Coder 是否继承 runtime 属性）
2. `/clear` 后 langchain runtime 是否正确清空上下文
3. 工具审批在 langchain 交互模式中的阻塞行为
4. KeyboardInterrupt 双击退出是否正确

### 10.2 依赖关系

交互模式本身没有硬性依赖，但建议在以下完成后实现：
- Phase 6（session 保存）— 已完成
- Phase 3（handle_tool_errors middleware）— 已完成

当前已具备实现条件。

### 10.3 设计验证清单

本设计回答了以下关键问题：

| 问题 | 答案 |
|------|------|
| 交互循环挂在哪里 | Layer 2（`base_coder.py:run()`），与 legacy 相同 |
| TUI 是否同时支持 | 天然支持，不需要改 `rpc_io.py` |
| 每轮执行 | 与 `--message` 一次性模式相同 |
| session 保存 | 与 Phase 6 相同逻辑 |
| 工具审批 | 复用 `ToolExecutor._request_approval()` |
| streaming | 本阶段不支持，降级为同步输出 |
| slash commands | 通过 `get_input()` 天然继承 |
| 异常恢复 | try/except + continue，不保存错误响应 |
| SwitchCoder | 由 Layer 1 处理，新 Coder 继承 runtime |

### 10.4 实现阶段预览

代码变更预计：

| 文件 | 变更 | 行数 |
|------|------|------|
| `aicoder/coders/base_coder.py` | langchain 分支增加 else 块（交互循环） | ~15 行 |
| `aicoder/tests/test_langchain_runtime.py` | 新增交互循环测试 | ~30 行 |

不需要修改：
- `rpc_io.py`（TUI 已天然支持）
- `langchain_runtime/agent.py`（不需要改动）
- `main.py`（Layer 1 不需要改动）
- `commands.py`（slash commands 不需要改动）

---

## 附录：交互循环完整流程图

### CLI 模式

```
$ aicoder --runtime langchain
                    │
                    ▼
        main.py: Coder.create()
        coder.runtime = "langchain"
                    │
                    ▼
        main.py: while True ← Layer 1
          │
          ▼
        coder.run() ← Layer 2
          │
          ├─ show_announcements()
          ├─ runtime == "langchain"
          ├─ with_message is None → enter interactive loop
          │
          ▼
        while True: ← Layer 2 inner
          │
          ├─ um = get_input()      ← 读取输入 + slash commands
          │   ├─ /model → SwitchCoder → 返回 Layer 1
          │   ├─ /clear → 清空消息，continue
          │   ├─ /help → 打印帮助，continue
          │   └─ "user text" → return text
          │
          ├─ text = run_langchain_agent(self, um)
          │   └─ LangChain agent 内部工具循环 ← Layer 3
          │
          ├─ io.print_assistant_output(text)
          │
          ├─ session 保存 (if session_id)
          │   ├─ cur_messages.append(user)
          │   ├─ cur_messages.append(assistant)
          │   ├─ done_messages.extend(cur_messages)
          │   ├─ cur_messages = []
          │   └─ _save_session()
          │
          ├─ KeyboardInterrupt → keyboard_interrupt()
          ├─ SwitchCoder → return (Layer 1 处理)
          ├─ Exception → io.tool_error(), continue
          └─ EOFError → return None (Layer 1 break)
```

### TUI 模式（已天然支持）

```
$ aicoder --runtime langchain --serve
                    │
                    ▼
        main.py: coder.runtime = "langchain"
        rpc_io.serve(coder) ← 自身循环
          │
          ▼
        while self._running:
          │
          ├─ get_input() → input/request → 阻塞
          │   └─ TUI 返回 input/submit {"content": "..."}
          │
          ├─ slash commands 内联处理
          │
          ├─ coder.run(with_message=user_input)
          │   └─ langchain 分支 → run_langchain_agent() + session 保存
          │
          ├─ status/update {"phase": "idle"}
          │
          └─ /quit → break
```

## 附录：文件行号索引

| 文件 | 逻辑 | 行号 |
|------|------|------|
| `main.py` | CLI 外层循环（Layer 1） | 386-406 |
| `main.py` | `--serve` 路径 | 371-379 |
| `main.py` | `coder.runtime` 设置 | 373 |
| `base_coder.py` | `run()` langchain 分支 | 300-322 |
| `base_coder.py` | `run()` legacy 交互循环 | 329-337 |
| `base_coder.py` | `get_input()` | 340-347 |
| `base_coder.py` | `keyboard_interrupt()` | 391 |
| `base_coder.py` | `_save_session()` | 338-358 |
| `commands.py` | `SwitchCoder` | 20-23 |
| `commands.py` | `/model` cmd | 216-237 |
| `commands.py` | `/clear` cmd | 359-363 |
| `commands.py` | `/resume` cmd | 383-399 |
| `io.py` | `get_input()` CLI 读取 | 53-71 |
| `rpc_io.py` | `serve()` TUI 循环 | 303-381 |
| `rpc_io.py` | `get_input()` RPC 阻塞 | 210 |
| `agent_runtime.py` | `run_user_turn()` | 22-45 |
| `agent_runtime.py` | `_finalize_on_error()` | 47-52 |
| `langchain_runtime/agent.py` | `run_langchain_agent()` | 95-100 |
