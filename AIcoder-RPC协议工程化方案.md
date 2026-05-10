# AIcoder RPC 协议工程化方案

## 0. 结论

当前不建议更换通信框架。

当前项目的前后端通信方式：

```text
JSON-RPC over stdio
```

对于本地 AI coding CLI 来说，这是合理且主流的方案。

当前真正需要做的是：

```text
把现有 RPC 协议工程化、类型化、版本化、可测试化。
```

---

## 1. 当前通信架构

### 1.1 后端

后端文件：

```text
aicoder/rpc_io.py
```

职责：

1. 从 stdin 读取 JSON-RPC 请求
2. 向 stdout 写 JSON-RPC notification/response
3. 接收用户输入
4. 发送 assistant streaming
5. 发送工具调用事件
6. 发送审批请求
7. 发送状态更新

### 1.2 前端

前端文件：

```text
aicoder-tui/src/rpc/client.ts
aicoder-tui/src/rpc/methods.ts
aicoder-tui/src/rpc/protocol.ts
aicoder-tui/src/hooks/useBackend.ts
```

职责：

1. 启动 Python 后端子进程
2. 发送 JSON-RPC request
3. 监听 backend notification
4. 更新 Zustand store
5. 响应审批和输入

---

## 2. 为什么不换通信框架

### 2.1 不建议换 FastAPI/WebSocket

原因：

1. 当前产品不是 Web App
2. 本地 TUI 不需要 HTTP server
3. 增加端口、鉴权、生命周期管理复杂度
4. 对 Claude Code 风格 CLI 没有直接收益

### 2.2 不建议换 gRPC

原因：

1. 当前通信不是高吞吐服务间调用
2. gRPC 对 TUI 子进程通信偏重
3. Python/Node 两端生成代码会增加维护成本

### 2.3 不建议立刻换 MCP

原因：

1. MCP 更适合插件/工具生态协议
2. 当前问题是前后端内部通信规范
3. 可以未来把工具层 MCP 化，但不应替代 TUI 内部 RPC

### 2.4 保留 stdio JSON-RPC 的优势

1. 本地子进程通信简单
2. 不占用端口
3. 易调试
4. 跨平台
5. 与 CLI 生命周期天然绑定
6. 适合 streaming token 和工具事件

---

## 3. 工程化目标

协议工程化后应具备：

1. 明确协议版本
2. 明确 request/response/notification 分类
3. 明确事件 schema
4. 前后端类型一致
5. 错误结构统一
6. 支持能力协商
7. 支持灰度新增字段
8. 支持测试
9. 支持日志和调试

---

## 4. 目标目录结构

### 4.1 后端新增目录

```text
aicoder/rpc/
  __init__.py
  protocol.py
  schemas.py
  dispatcher.py
  events.py
  errors.py
  version.py
```

### 4.2 前端保留并增强

```text
aicoder-tui/src/rpc/
  client.ts
  methods.ts
  protocol.ts
  schemas.ts
  version.ts
```

---

## 5. 协议版本设计

### 5.1 后端版本

新增：

```text
aicoder/rpc/version.py
```

内容：

```python
RPC_PROTOCOL_VERSION = "1.0.0"
RPC_PROTOCOL_NAME = "aicoder-rpc"
```

### 5.2 前端版本

新增：

```text
aicoder-tui/src/rpc/version.ts
```

内容：

```ts
export const RPC_PROTOCOL_NAME = "aicoder-rpc";
export const RPC_PROTOCOL_VERSION = "1.0.0";
```

### 5.3 ready 事件必须带版本

后端 `ready` notification：

```json
{
  "protocol": {
    "name": "aicoder-rpc",
    "version": "1.0.0"
  },
  "model": "deepseek/deepseek-chat",
  "mode": "act",
  "planMode": false,
  "capabilities": {
    "streaming": true,
    "tools": true,
    "approval": true,
    "sessions": true,
    "models": true
  }
}
```

---

## 6. 消息分类

### 6.1 Request

前端发给后端，必须有 response。

| Method | 方向 | 说明 |
|---|---|---|
| `input/submit` | TUI -> Backend | 提交用户输入 |
| `approval/respond` | TUI -> Backend | 响应工具审批 |
| `confirm/respond` | TUI -> Backend | 响应普通确认 |
| `cancel/generation` | TUI -> Backend | 取消生成 |
| `model/list` | TUI -> Backend | 获取模型列表 |
| `session/list` | TUI -> Backend | 获取会话列表 |
| `session/new` | TUI -> Backend | 新建会话 |
| `session/resume` | TUI -> Backend | 恢复会话 |
| `rpc/ping` | TUI -> Backend | 健康检查 |
| `rpc/capabilities` | TUI -> Backend | 获取能力 |

### 6.2 Notification

后端发给前端，无 response。

| Method | 方向 | 说明 |
|---|---|---|
| `ready` | Backend -> TUI | 后端准备完成 |
| `shutdown` | Backend -> TUI | 后端关闭 |
| `status/update` | Backend -> TUI | 状态更新 |
| `stream/token` | Backend -> TUI | 流式 token |
| `stream/finalize` | Backend -> TUI | 一条 assistant 消息完成 |
| `assistant/output` | Backend -> TUI | 非流式 assistant 输出 |
| `tool/call_started` | Backend -> TUI | 工具调用开始 |
| `tool/call_finished` | Backend -> TUI | 工具调用结束 |
| `approval/request` | Backend -> TUI | 审批请求 |
| `confirm/ask` | Backend -> TUI | 普通确认请求 |
| `input/request` | Backend -> TUI | 请求用户输入 |
| `tool/output` | Backend -> TUI | 工具普通输出 |
| `tool/error` | Backend -> TUI | 工具错误输出 |
| `tool/warning` | Backend -> TUI | 工具警告输出 |
| `error` | Backend -> TUI | 通用错误 |
| `debug/log` | Backend -> TUI | 调试日志 |

---

## 7. 统一 JSON-RPC Envelope

### 7.1 Request

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "input/submit",
  "params": {}
}
```

### 7.2 Response

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {}
}
```

### 7.3 Error Response

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "error": {
    "code": -32601,
    "message": "Unknown method",
    "data": {
      "method": "unknown/method"
    }
  }
}
```

### 7.4 Notification

```json
{
  "jsonrpc": "2.0",
  "method": "stream/token",
  "params": {
    "text": "hello"
  }
}
```

---

## 8. 核心事件 Schema

## 8.1 `ready`

```ts
export interface ReadyNotification {
  protocol: {
    name: "aicoder-rpc";
    version: string;
  };
  model: string;
  mode: PermissionMode;
  planMode: boolean;
  capabilities: RpcCapabilities;
}
```

## 8.2 `status/update`

```ts
export type PermissionMode =
  | "act"
  | "plan"
  | "default"
  | "acceptEdits"
  | "bypassPermissions";

export interface StatusUpdateNotification {
  model?: string;
  mode?: PermissionMode;
  planMode?: boolean;
  phase?: string;
  tokens?: number;
  cost?: number;
  sessionId?: string;
}
```

## 8.3 `stream/token`

```ts
export interface StreamTokenNotification {
  text: string;
  messageId?: string;
}
```

## 8.4 `stream/finalize`

```ts
export interface StreamFinalizeNotification {
  text: string;
  messageId?: string;
  is_intermediate?: boolean;
}
```

## 8.5 `tool/call_started`

```ts
export interface ToolCallStartedNotification {
  id?: string;
  tool: string;
  args: Record<string, unknown>;
  mode?: PermissionMode;
}
```

## 8.6 `tool/call_finished`

```ts
export interface ToolCallFinishedNotification {
  id?: string;
  tool: string;
  result: string;
  success: boolean;
  rejected?: boolean;
  error?: string;
  meta?: Record<string, unknown>;
}
```

## 8.7 `approval/request`

第一阶段兼容版：

```ts
export interface ApprovalRequestNotification {
  id: string;
  question: string;
  diff?: string;
}
```

第二阶段结构化版：

```ts
export interface ApprovalRequestNotificationV2 {
  id: string;
  kind: "tool" | "command" | "plan";
  question: string;
  tool?: string;
  args?: Record<string, unknown>;
  risk?: string;
  diff?: string;
  mode?: PermissionMode;
}
```

## 8.8 `error`

```ts
export interface ErrorNotification {
  message: string;
  code?: string;
  recoverable?: boolean;
  detail?: string;
}
```

---

## 9. 后端改造方案

### 9.1 第一阶段：不拆文件，只规范字段

先修改：

```text
aicoder/rpc_io.py
```

要求：

1. `ready` 加协议版本
2. `status/update` 加 `mode`
3. `tool/call_started` 加可选 id
4. `tool/call_finished` 加可选 rejected/error/meta
5. 新增 `rpc/ping`
6. 新增 `rpc/capabilities`

### 9.2 第二阶段：拆出协议模块

新增：

```text
aicoder/rpc/version.py
aicoder/rpc/errors.py
aicoder/rpc/events.py
aicoder/rpc/schemas.py
```

保留 `rpc_io.py` 作为 IO 实现。

### 9.3 第三阶段：Dispatcher

新增：

```text
aicoder/rpc/dispatcher.py
```

把当前 `_handle_request` 中的 if/else 改成路由表：

```python
HANDLERS = {
    "input/submit": handle_input_submit,
    "approval/respond": handle_approval_respond,
    "confirm/respond": handle_confirm_respond,
    "session/list": handle_session_list,
    "session/new": handle_session_new,
    "session/resume": handle_session_resume,
    "model/list": handle_model_list,
    "rpc/ping": handle_rpc_ping,
    "rpc/capabilities": handle_rpc_capabilities,
}
```

好处：

1. 请求处理更清晰
2. 更好测试
3. 以后新增方法不污染 `rpc_io.py`

---

## 10. 前端改造方案

### 10.1 修改协议类型

修改：

```text
aicoder-tui/src/rpc/protocol.ts
```

目标：

1. 明确 request 类型
2. 明确 notification 类型
3. 增加 `ReadyNotification`
4. 增加 `PermissionMode`
5. 增加 `RpcCapabilities`

### 10.2 新增 schema 文件

新增：

```text
aicoder-tui/src/rpc/schemas.ts
```

第一阶段可以只放 TypeScript 类型，不引入 zod。

第二阶段再考虑 runtime validation。

### 10.3 修改 methods

修改：

```text
aicoder-tui/src/rpc/methods.ts
```

新增：

```ts
ping(): Promise<{ ok: true }>;
getCapabilities(): Promise<RpcCapabilities>;
```

### 10.4 修改 useBackend

修改：

```text
aicoder-tui/src/hooks/useBackend.ts
```

要求：

1. `ready` 时检查协议版本
2. 版本不兼容时显示 error
3. `status/update` 更新 mode/phase
4. 对未知 notification 保持容忍

---

## 11. 能力协商

### 11.1 能力类型

```ts
export interface RpcCapabilities {
  streaming: boolean;
  tools: boolean;
  approval: boolean;
  sessions: boolean;
  models: boolean;
  modes?: string[];
  structuredApproval?: boolean;
  langGraphRuntime?: boolean;
}
```

### 11.2 后端返回

```json
{
  "streaming": true,
  "tools": true,
  "approval": true,
  "sessions": true,
  "models": true,
  "modes": ["act", "plan"],
  "structuredApproval": false,
  "langGraphRuntime": false
}
```

### 11.3 用途

前端可以根据 capabilities 决定：

1. 是否显示 model picker
2. 是否显示 approval UI
3. 是否显示 mode switcher
4. 是否使用结构化审批
5. 是否显示 graph phase

---

## 12. 错误码规范

### 12.1 JSON-RPC 标准错误码

| Code | 含义 |
|---|---|
| `-32700` | Parse error |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |

### 12.2 项目自定义错误码

建议使用 `-32000` 到 `-32099`。

| Code | 含义 |
|---|---|
| `-32001` | Backend not ready |
| `-32002` | Generation cancelled |
| `-32003` | Approval timeout |
| `-32004` | Session not found |
| `-32005` | Model error |
| `-32006` | Tool execution error |
| `-32007` | Permission denied |

---

## 13. 测试计划

### 13.1 后端测试

新增：

```text
aicoder/tests/test_rpc_protocol.py
aicoder/tests/test_rpc_dispatcher.py
```

必测：

1. `ready` 包含 protocol/capabilities
2. `rpc/ping` 返回 ok
3. 未知 method 返回 `-32601`
4. `status/update` 包含 mode
5. `approval/respond` 能唤醒 pending response

### 13.2 前端测试

新增或修改：

```text
aicoder-tui/src/rpc/protocol.test.ts
aicoder-tui/src/rpc/methods.test.ts
```

必测：

1. `ReadyNotification` 类型兼容
2. `status/update` 可更新 mode
3. `approval/request` 旧版字段仍可用

### 13.3 手工测试

启动 TUI 后验证：

```text
ready -> status/update -> input/request -> input/submit -> stream/token -> stream/finalize
```

工具调用验证：

```text
tool/call_started -> tool/call_finished
```

审批验证：

```text
approval/request -> approval/respond
```

---

## 14. 分阶段执行方案

## 阶段 1：协议字段补齐

修改：

```text
aicoder/rpc_io.py
aicoder-tui/src/rpc/protocol.ts
aicoder-tui/src/stores/configStore.ts
aicoder-tui/src/hooks/useBackend.ts
```

任务：

1. `ready` 加 protocol/capabilities
2. `status/update` 加 mode/phase
3. 前端协议类型补齐
4. 前端 store 接收 mode/phase
5. 增加 `rpc/ping`
6. 增加 `rpc/capabilities`

验收：

```powershell
pytest aicoder/tests -q
cd aicoder-tui
cmd /c npm run typecheck
```

注意：

如果前端已有既存 TS 错误，需要记录并区分新增错误。

---

## 阶段 2：拆出协议模块

新增：

```text
aicoder/rpc/
```

任务：

1. 新增 `version.py`
2. 新增 `errors.py`
3. 新增 `events.py`
4. 新增 `schemas.py`
5. `rpc_io.py` 改为引用这些常量和构造函数

验收：

```powershell
pytest aicoder/tests/test_rpc_protocol.py -q
```

---

## 阶段 3：请求 Dispatcher

新增：

```text
aicoder/rpc/dispatcher.py
```

任务：

1. 把 `_handle_request` 拆出
2. 建立 method handler map
3. 每个 handler 单独测试
4. `rpc_io.py` 只负责收发和 pending response

验收：

```powershell
pytest aicoder/tests/test_rpc_dispatcher.py -q
```

---

## 阶段 4：结构化审批协议

任务：

1. `approval/request` 增加 `kind/tool/args/risk/mode`
2. 前端保持旧字段兼容
3. Approval UI 优先展示结构化字段
4. 后端仍支持只传 `question/diff`

验收：

1. 旧审批请求可显示
2. 新审批请求可显示
3. approve/reject 正常回传

---

## 阶段 5：协议文档常态化

新增：

```text
docs/rpc-protocol.md
```

内容：

1. 协议版本
2. request 列表
3. notification 列表
4. schema
5. 错误码
6. 兼容策略

---

## 15. 兼容策略

### 15.1 字段只增不删

新增字段必须 optional。

例如：

```ts
mode?: PermissionMode;
phase?: string;
```

### 15.2 旧前端兼容新后端

旧前端忽略未知字段。

### 15.3 新前端兼容旧后端

新前端如果没有收到：

```text
protocol
capabilities
mode
```

则使用默认值：

```ts
mode = planMode ? "plan" : "act";
capabilities = defaultCapabilities;
```

---

## 16. 给执行者的具体任务清单

请按顺序执行：

1. 修改后端 `ready` notification，加入 `protocol` 和 `capabilities`
2. 修改后端 `status/update`，加入 `mode` 和 `phase`
3. 后端新增 `rpc/ping`
4. 后端新增 `rpc/capabilities`
5. 前端 `protocol.ts` 补齐类型
6. 前端 `configStore.ts` 增加 `phase` 和更完整的 `mode`
7. 前端 `useBackend.ts` 处理新版 `ready`
8. 新增后端 RPC 协议测试
9. 再拆 `aicoder/rpc/` 模块
10. 最后做结构化审批升级

---

## 17. 最小完成标准

第一版完成后应满足：

1. 现有 TUI 正常启动
2. 后端 `ready` 带协议版本
3. 前端能识别协议能力
4. 当前模式能稳定显示
5. 工具调用事件不变
6. 审批流程不变
7. 所有后端测试通过

---

## 18. 最终建议

当前通信层最优路线是：

```text
继续 JSON-RPC over stdio
  -> 补协议版本
  -> 补类型 schema
  -> 拆 dispatcher
  -> 结构化事件
  -> 文档化
```

不要急着换成：

1. FastAPI
2. WebSocket
3. gRPC
4. MCP

这些都可以以后作为扩展通道，但不应替代当前本地 TUI 与本地后端之间的主通信方式。
