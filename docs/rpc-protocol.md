# RPC 协议文档

## 概述

aicoder 后端（Python）与 aicoder-tui 前端（TypeScript）通过 **JSON-RPC 2.0 over stdio** 通信。

- **传输层**: Python 子进程 stdin/stdout，每行一个 JSON 消息
- **字符编码**: UTF-8（前后端均强制）
- **启动**: TUI spawn `python -m aicoder --serve`，后端输出第一条 `ready` notification 后开始交互
- **stderr**: 后端调试日志输出到 stderr，不参与 JSON-RPC 协议

## 协议文件对照

| 方向 | Python | TypeScript |
|------|--------|------------|
| 传输 | `aicoder/rpc_io.py` | `aicoder-tui/src/rpc/transport.ts` |
| 协议类型 | — | `aicoder-tui/src/rpc/protocol.ts` |
| 方法绑定 | `aicoder/rpc_io.py` `_handle_request()` | `aicoder-tui/src/rpc/methods.ts` |
| 消息分发 | `JsonRpcIO` | `aicoder-tui/src/rpc/client.ts` |
| 状态管理 | `JsonRpcIO.serve()` | `aicoder-tui/src/hooks/useBackend.ts` |

---

## 后端 → TUI 通知（Notification）

后端单向推送，无需 TUI 回复。

### `ready`
后端启动完成。
```json
{"jsonrpc":"2.0","method":"ready","params":{"model":"claude-sonnet-4-6","planMode":false,"mode":"act","yolo":false,"phase":"idle"}}
```

### `status/update`
状态变更广播。
```json
{"jsonrpc":"2.0","method":"status/update","params":{"model":"claude-sonnet-4-6","planMode":false,"mode":"act","yolo":false,"phase":"planning"}}
```
**phase 取值**: `"idle"` | `"planning"` | `"acting"`

### `input/request`
请求用户输入，附带上下文信息。
```json
{"jsonrpc":"2.0","method":"input/request","params":{"root":"/path/to/project","inchat_files":["main.py"],"addable_files":["utils.py"],"commands":["/help","/clear"]}}
```

### `stream/token`
流式输出 token。
```json
{"jsonrpc":"2.0","method":"stream/token","params":{"text":"Hello"}}
```

### `stream/finalize`
流式输出完成。
```json
{"jsonrpc":"2.0","method":"stream/finalize","params":{"text":"full response text","is_intermediate":false}}
```

### `assistant/output`
非流式完整输出。
```json
{"jsonrpc":"2.0","method":"assistant/output","params":{"text":"complete response"}}
```

### `tool/call_started`
工具调用开始。
```json
{"jsonrpc":"2.0","method":"tool/call_started","params":{"tool":"write_file","args":{"path":"main.py","content":"..."}}}
```

### `tool/call_finished`
工具调用结束。
```json
{"jsonrpc":"2.0","method":"tool/call_finished","params":{"tool":"write_file","result":"File written","success":true}}
```

### `tool/output`
工具执行中间输出。
```json
{"jsonrpc":"2.0","method":"tool/output","params":{"message":"Running lint...","bold":false}}
```

### `tool/error`
工具执行错误。
```json
{"jsonrpc":"2.0","method":"tool/error","params":{"message":"File not found"}}
```

### `tool/warning`
工具执行警告。
```json
{"jsonrpc":"2.0","method":"tool/warning","params":{"message":"Deprecated API used"}}
```

### `approval/request`
文件编辑/危险操作审批请求。TUI 需回 `approval/respond`。
```json
{"jsonrpc":"2.0","method":"approval/request","params":{"id":"uuid-123","question":"Allow write to main.py?","diff":"--- a/main.py\n+++ b/main.py\n..."}}
```

### `confirm/ask`
确认对话。TUI 需回 `confirm/respond`。
```json
{"jsonrpc":"2.0","method":"confirm/ask","params":{"id":"uuid-456","question":"Continue?","default":"y"}}
```

### `error`
后端运行时错误。
```json
{"jsonrpc":"2.0","method":"error","params":{"message":"API rate limit exceeded"}}
```

### `shutdown`
后端即将退出。
```json
{"jsonrpc":"2.0","method":"shutdown","params":{}}
```

---

## TUI → 后端请求（Request）

TUI 发送带 `id` 的请求，后端回复对应 response。

### `input/submit`
提交用户输入。
```json
→ {"jsonrpc":"2.0","id":1,"method":"input/submit","params":{"text":"fix the bug"}}
← {"jsonrpc":"2.0","id":1,"result":{"status":"ok"}}
```

### `cancel/generation`
取消当前生成。
```json
→ {"jsonrpc":"2.0","id":2,"method":"cancel/generation","params":{}}
← {"jsonrpc":"2.0","id":2,"result":{"status":"ok"}}
```

### `approval/respond`
回复审批请求。
```json
→ {"jsonrpc":"2.0","id":3,"method":"approval/respond","params":{"id":"uuid-123","approved":true}}
← {"jsonrpc":"2.0","id":3,"result":{"status":"ok"}}
```

### `confirm/respond`
回复确认对话。
```json
→ {"jsonrpc":"2.0","id":4,"method":"confirm/respond","params":{"id":"uuid-456","confirmed":true}}
← {"jsonrpc":"2.0","id":4,"result":{"status":"ok"}}
```

### `model/list`
列出可用模型。
```json
→ {"jsonrpc":"2.0","id":5,"method":"model/list","params":{}}
← {"jsonrpc":"2.0","id":5,"result":{"models":["claude-sonnet-4-6","claude-opus-4-7"],"currentModel":"claude-sonnet-4-6"}}
```

### `model/switch`
切换模型。
```json
→ {"jsonrpc":"2.0","id":6,"method":"model/switch","params":{"model":"claude-opus-4-7"}}
← {"jsonrpc":"2.0","id":6,"result":{"status":"ok"}}
```

### `session/list`
列出历史会话。
```json
→ {"jsonrpc":"2.0","id":7,"method":"session/list","params":{}}
← {"jsonrpc":"2.0","id":7,"result":[{"id":"abc","title":"Bug fix","created":"2026-01-01"}]}
```

### `session/new`
新建会话（等同 `/clear`）。
```json
→ {"jsonrpc":"2.0","id":8,"method":"session/new","params":{}}
← {"jsonrpc":"2.0","id":8,"result":{"status":"ok"}}
```

### `session/resume`
恢复历史会话。
```json
→ {"jsonrpc":"2.0","id":9,"method":"session/resume","params":{"id":"abc"}}
← {"jsonrpc":"2.0","id":9,"result":{"status":"ok"}}
```

---

## 前后端一致性对照

| 字段 | Python 端 | TS 端 | 一致 |
|------|-----------|-------|------|
| `approval/request.id` | `uuid4()` string | `{ id: string }` | ✅ |
| `approval/respond.approved` | `bool` | `boolean` | ✅ |
| `confirm/ask.id` | `uuid4()` string | `{ id: string }` | ✅ |
| `confirm/ask.default` | `"y"` string | 缺少 `default` 字段 | ⚠️ |
| `confirm/respond.confirmed` | `bool` | `boolean` | ✅ |
| `model/list` response | `{ models, currentModel }` | `ModelListResponse` | ✅ |
| `status/update.phase` | `"idle"/"planning"/"acting"` | `string` | ✅ |
| `status/update.mode` | `"plan"/"act"` | `"plan" | "act"` | ✅ |
| `stream/finalize.is_intermediate` | `bool` | `boolean` | ✅ |
| `tool/call_finished.success` | `bool` | `boolean` | ✅ |
| `tool/warning` | 后端有发送 | TS 有监听 | ✅ |
| `user_input` | 后端有（log_only时跳过） | TS 无监听 | N/A |
| `parse_error` | 后端有发送 | TS 无监听 | N/A |

## 已知差异

1. **`confirm/ask.default`** — Python 发送 `default` 字段，但 TS `BackendNotifications` 类型未声明。建议补齐。
2. **`user_input`** — Python 在 `log_only=False` 时发送，TS 未监听。当前无影响。
3. **`parse_error`** — Python 在 JSON 解析失败时发送，TS 未监听。建议补齐用于错误展示。
