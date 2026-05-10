# Ink 改造 TUI 实施方案

## 0. 说明

这里的 `Ink` 指官方开源 TUI 框架：

```text
https://github.com/vadimdemedes/ink
```

Ink 是 React 风格的终端 UI 框架，适合构建类似 Claude Code、Codex CLI、Gemini CLI 这类交互式 AI coding CLI。

注意：

```text
Ink 改造的是前端 TUI，不是后端。
```

当前项目后端仍然是：

```text
aicoder/
```

当前项目 TUI 前端是：

```text
aicoder-tui/
```

本方案目标是：

1. 尽量从当前自研/复制版 Ink 层迁回官方 Ink
2. 保留现有 Python 后端和 JSON-RPC 通信
3. 重做 TUI 的交互层、状态层、审批层、工具卡片层
4. 让前端体验更接近 Claude Code 风格

---

## 1. 当前 TUI 判断

当前项目的 TUI 目录：

```text
aicoder-tui/
```

当前已经存在大量类似 Ink 的代码：

```text
aicoder-tui/src/ink/
```

这说明当前项目可能不是直接使用官方 `ink` 包，而是维护了一套本地 terminal renderer / Ink-like 实现。

这会带来几个问题：

1. 维护成本高
2. TypeScript 类型错误多
3. React runtime 兼容成本高
4. 后续做复杂 UI 时容易卡在底层渲染问题
5. 不利于快速迭代 Claude Code 式交互

所以建议分阶段迁到官方 Ink。

---

## 2. 改造目标

### 2.1 第一目标

把当前 TUI 从“自研 terminal renderer”逐步迁移到：

```text
official Ink + React + Zustand + JSON-RPC client
```

### 2.2 第二目标

保留现有交互能力：

1. 输入用户消息
2. 显示 assistant 流式输出
3. 显示工具调用
4. 显示工具结果
5. 显示审批弹窗
6. 显示当前 model
7. 显示当前 mode
8. 支持 slash command

### 2.3 第三目标

增强为 Claude Code 风格：

1. 状态栏更清晰
2. Plan/Act 模式明显
3. 工具调用卡片更紧凑
4. 审批 UI 更结构化
5. 输入区更像命令工作台
6. 长输出可折叠

---

## 3. 总体策略

不要一次性删除当前 `src/ink/`。

推荐策略：

```text
保留旧 TUI
  -> 新建 official Ink app
  -> 复用现有 RPC/store
  -> 逐步替换组件
  -> 默认切换到新 TUI
  -> 删除旧 renderer
```

通过环境变量或命令参数灰度：

```text
AICODER_TUI_RUNTIME=official-ink
```

---

## 4. 依赖改造

### 4.1 修改文件

```text
aicoder-tui/package.json
```

### 4.2 新增依赖

建议加入：

```json
{
  "dependencies": {
    "ink": "^5.0.0",
    "ink-text-input": "^6.0.0",
    "ink-select-input": "^6.0.0",
    "ink-spinner": "^5.0.0",
    "ink-link": "^4.0.0",
    "ink-use-stdout-dimensions": "^1.0.0",
    "react": "^19.0.0",
    "zustand": "^5.0.0"
  }
}
```

如果官方 Ink 版本和 React 版本冲突，优先按 Ink 当前 peer dependency 调整。

### 4.3 安装

在：

```text
D:\CodingProject\aiCoder\aicoder-tui
```

执行：

```powershell
cmd /c npm install
```

如果项目使用 pnpm，则执行：

```powershell
cmd /c pnpm install
```

---

## 5. 新目录设计

建议新增一套 official Ink 入口，不直接改旧入口。

```text
aicoder-tui/src/official-ink/
  App.tsx
  index.tsx
  components/
    ChatView.tsx
    MessageBlock.tsx
    StatusBar.tsx
    InputBox.tsx
    ApprovalPanel.tsx
    ToolCallCard.tsx
    PlanBlock.tsx
    SlashCommandMenu.tsx
    ModelPicker.tsx
  hooks/
    useOfficialBackend.ts
    useKeyboardShortcuts.ts
  layout/
    MainLayout.tsx
  theme.ts
```

保留现有：

```text
aicoder-tui/src/rpc/
aicoder-tui/src/stores/
```

---

## 6. 入口改造

### 6.1 当前入口

当前入口可能是：

```text
aicoder-tui/src/index.tsx
```

### 6.2 新增 official Ink 入口

新增：

```text
aicoder-tui/src/official-ink/index.tsx
```

示例：

```tsx
import React from "react";
import { render } from "ink";
import { App } from "./App.js";

render(<App />);
```

### 6.3 修改主入口做运行时分支

在：

```text
aicoder-tui/src/index.tsx
```

增加：

```ts
if (process.env.AICODER_TUI_RUNTIME === "official-ink") {
  await import("./official-ink/index.js");
} else {
  await import("./tui.js");
}
```

具体路径按当前项目实际入口调整。

---

## 7. App 组件设计

新增：

```text
aicoder-tui/src/official-ink/App.tsx
```

职责：

1. 启动后端连接
2. 订阅 RPC 事件
3. 渲染主布局
4. 管理全局退出

示例结构：

```tsx
import React, { useEffect } from "react";
import { Box } from "ink";
import { MainLayout } from "./layout/MainLayout.js";
import { useOfficialBackend } from "./hooks/useOfficialBackend.js";

export function App() {
  const { connect, disconnect } = useOfficialBackend();

  useEffect(() => {
    void connect();
    return () => {
      void disconnect();
    };
  }, [connect, disconnect]);

  return (
    <Box flexDirection="column" height="100%">
      <MainLayout />
    </Box>
  );
}
```

---

## 8. Layout 设计

新增：

```text
aicoder-tui/src/official-ink/layout/MainLayout.tsx
```

布局：

```text
┌──────────────────────────────┐
│ ChatView                     │
│                              │
├──────────────────────────────┤
│ ApprovalPanel / Tool Status  │
├──────────────────────────────┤
│ InputBox                     │
├──────────────────────────────┤
│ StatusBar                    │
└──────────────────────────────┘
```

组件：

```tsx
import React from "react";
import { Box } from "ink";
import { ApprovalPanel } from "../components/ApprovalPanel.js";
import { ChatView } from "../components/ChatView.js";
import { InputBox } from "../components/InputBox.js";
import { StatusBar } from "../components/StatusBar.js";

export function MainLayout() {
  return (
    <Box flexDirection="column" height="100%">
      <Box flexGrow={1} overflow="hidden">
        <ChatView />
      </Box>
      <ApprovalPanel />
      <InputBox />
      <StatusBar />
    </Box>
  );
}
```

---

## 9. 状态层复用

优先复用当前 store：

```text
aicoder-tui/src/stores/chatStore.ts
aicoder-tui/src/stores/configStore.ts
aicoder-tui/src/stores/approvalStore.ts
```

第一阶段不要重写 store。

只新增必要字段：

```ts
phase?: string;
mode: "plan" | "act" | "default" | "acceptEdits" | "bypassPermissions";
```

---

## 10. RPC 复用

继续复用：

```text
aicoder-tui/src/rpc/client.ts
aicoder-tui/src/rpc/methods.ts
aicoder-tui/src/rpc/protocol.ts
```

新增 hook：

```text
aicoder-tui/src/official-ink/hooks/useOfficialBackend.ts
```

可以先复制当前：

```text
aicoder-tui/src/hooks/useBackend.ts
```

然后删掉和旧 renderer 强绑定的逻辑。

目标：

1. `stream/token` 写入 `chatStore`
2. `stream/finalize` 完成消息
3. `tool/call_started` 写入工具卡片
4. `tool/call_finished` 更新工具卡片
5. `approval/request` 写入 `approvalStore`
6. `status/update` 写入 `configStore`

---

## 11. ChatView 设计

新增：

```text
aicoder-tui/src/official-ink/components/ChatView.tsx
```

职责：

1. 读取 `chatStore.messages`
2. 渲染用户消息
3. 渲染 assistant 消息
4. 渲染 tool call
5. 渲染 streamingText

第一版不做虚拟列表。

后续再做：

1. 滚动
2. 折叠
3. 长输出截断
4. 搜索

---

## 12. ToolCallCard 设计

新增：

```text
aicoder-tui/src/official-ink/components/ToolCallCard.tsx
```

显示字段：

1. tool name
2. status
3. 参数摘要
4. 结果摘要
5. success/error

推荐视觉：

```text
● read_file  done
  path: aicoder/tools/executor.py
  Loaded file content for inspection.
```

不要一开始做复杂边框。

终端 UI 里紧凑比花哨更重要。

---

## 13. ApprovalPanel 设计

新增：

```text
aicoder-tui/src/official-ink/components/ApprovalPanel.tsx
```

职责：

1. 读取 `approvalStore.pending`
2. 如果没有 pending，不渲染
3. 如果有 pending，显示问题和 diff 摘要
4. 支持快捷键：
   - `y` approve
   - `n` reject
   - `esc` reject

需要调用：

```ts
getBackendApi()?.respondApproval(id, approved)
```

如果当前 API 名不同，按：

```text
aicoder-tui/src/rpc/methods.ts
```

实际方法调整。

---

## 14. InputBox 设计

新增：

```text
aicoder-tui/src/official-ink/components/InputBox.tsx
```

建议使用：

```text
ink-text-input
```

功能：

1. 普通输入
2. Enter 发送
3. `/` 触发 slash menu
4. 上下键历史记录
5. 禁用状态下显示 waiting

第一阶段只做：

1. 输入
2. Enter 发送
3. 后端未连接时禁用

---

## 15. StatusBar 设计

新增：

```text
aicoder-tui/src/official-ink/components/StatusBar.tsx
```

显示：

```text
ACT | model-name | ready
PLAN | model-name | streaming
```

后续显示：

1. cwd
2. session id
3. token usage
4. cost
5. checkpoint

---

## 16. PlanBlock 设计

新增：

```text
aicoder-tui/src/official-ink/components/PlanBlock.tsx
```

如果 assistant 文本包含：

```text
Plan:
Findings:
Next step:
```

则渲染成计划块。

注意：

1. 不要写解释性 UI 文案
2. 只展示内容
3. 保持紧凑

---

## 17. SlashCommandMenu 设计

新增：

```text
aicoder-tui/src/official-ink/components/SlashCommandMenu.tsx
```

第一阶段可以暂不实现。

第二阶段实现：

1. 输入 `/` 后展示候选命令
2. 读取 `configStore.commands`
3. 上下键选择
4. Enter 补全

---

## 18. 后端需要配合的最小改造

Ink 改造主要在前端，但后端建议补充这些字段，方便新 UI 展示。

### 18.1 `status/update`

在：

```text
aicoder/rpc_io.py
```

确保发送：

```json
{
  "model": "xxx",
  "mode": "act",
  "planMode": false,
  "phase": "idle"
}
```

### 18.2 `tool/call_started`

确保发送：

```json
{
  "tool": "read_file",
  "args": {
    "path": "README.md"
  }
}
```

### 18.3 `tool/call_finished`

确保发送：

```json
{
  "tool": "read_file",
  "result": "Loaded file content for inspection.",
  "success": true
}
```

### 18.4 `approval/request`

第一阶段保持：

```json
{
  "id": "uuid",
  "question": "Allow tool call?",
  "diff": "..."
}
```

第二阶段增强：

```json
{
  "id": "uuid",
  "kind": "tool",
  "question": "Allow edit_file?",
  "tool": "edit_file",
  "args": {},
  "risk": "modifies files",
  "diff": "..."
}
```

---

## 19. 分阶段执行计划

## 阶段 1：安装官方 Ink 并建立新入口

任务：

1. 修改 `aicoder-tui/package.json`
2. 安装 `ink` 相关依赖
3. 新建 `src/official-ink/index.tsx`
4. 新建 `src/official-ink/App.tsx`
5. 新建 `src/official-ink/layout/MainLayout.tsx`
6. 主入口增加环境变量分支

验收：

```powershell
cd aicoder-tui
$env:AICODER_TUI_RUNTIME="official-ink"
cmd /c npm run dev
```

成功标准：

1. 新 Ink app 能启动
2. 旧 TUI 不受影响
3. 不连接后端时也能显示基础界面

---

## 阶段 2：接入 RPC 和 stores

任务：

1. 新建 `useOfficialBackend.ts`
2. 复用 `RpcClient`
3. 绑定所有现有事件
4. 确认 `chatStore`、`configStore`、`approvalStore` 可正常更新

验收：

1. 后端 ready 后状态栏显示 model
2. 用户输入能发送到后端
3. assistant streaming 能显示

---

## 阶段 3：实现核心 UI 组件

任务：

1. `ChatView`
2. `MessageBlock`
3. `InputBox`
4. `StatusBar`
5. `ToolCallCard`
6. `ApprovalPanel`

验收：

1. 能聊天
2. 能显示工具调用
3. 能显示工具结果
4. 能审批
5. 能显示 PLAN/ACT

---

## 阶段 4：补齐交互 ✅ 已完成

任务：

1. ✅ slash command menu（含 `/help`、`/exit`、`/quit`、`/compact`、`/yolo`，未知命令转发后端）
2. ✅ model picker（打开时自动从后端拉取模型列表，loading/error 状态）
3. ✅ 输入历史（↑↓ 键导航，最多 100 条）
4. ✅ cancel generation（Esc 取消流式输出，Ctrl+C 流式中取消/非流式退出）
5. ✅ 长输出截断（streaming text 最多 20 行/2000 字符，消息显示上限 200 条）

验收：

1. ✅ `/plan`、`/act` 易用
2. ✅ `/model` 可操作
3. ✅ 长工具输出不会刷屏

---

## 阶段 5：替换默认 TUI ✅ 已完成

任务：

1. ✅ 默认启用 official Ink（`src/index.tsx` 默认走 official-ink）
2. ✅ 保留旧 TUI fallback（`AICODER_TUI_RUNTIME=legacy` 回退旧 renderer）
3. ✅ 更新 bin 启动逻辑（`package.json` scripts: `dev:legacy`、`start:legacy`）
4. ✅ 清理未使用组件（移除未使用的 import、变量）

成功标准：

1. ✅ 默认启动新 TUI
2. ✅ 环境变量可回退旧 TUI
3. ✅ 常见任务不回归

---

## 20. 测试计划

### 20.1 前端单元测试

如果已有 vitest：

```text
aicoder-tui/src/official-ink/components/*.test.tsx
```

建议测：

1. `StatusBar` 显示 mode/model
2. `ToolCallCard` 显示 success/error
3. `ApprovalPanel` approve/reject 回调
4. `PlanBlock` 解析计划内容

### 20.2 手工测试

执行：

```powershell
cd aicoder-tui
$env:AICODER_TUI_RUNTIME="official-ink"
cmd /c npm run dev
```

测试用例：

```text
/plan
分析当前项目结构，不要修改文件
```

```text
/act
读取 README.md
```

```text
/act
创建一个 hello.txt，内容是 hello
```

### 20.3 后端测试

每次前端改造后仍需跑：

```powershell
pytest aicoder/tests -q
```

---

## 21. 风险和处理

### 21.1 Ink 版本与 React 版本冲突

处理：

1. 查 Ink peer dependency
2. 降级或升级 React
3. 不要同时维护两套 React runtime

### 21.2 当前本地 `src/ink/` 与官方 `ink` 命名冲突

处理：

1. 新组件中从 `"ink"` 导入
2. 不从 `"../../ink/index.js"` 导入
3. 旧组件保持原样

### 21.3 TypeScript 既存错误干扰验收

处理：

1. 记录迁移前 `npm run typecheck` 错误
2. 迁移后只对比新增错误
3. 优先让新 `official-ink` 目录类型正确

### 21.4 输入体验回归

处理：

1. 第一版只做稳定输入
2. 后续再做历史、补全、快捷键
3. 不要一开始追求复杂编辑器体验

---

## 22. 给执行者的具体任务清单

请按顺序执行：

1. 在 `aicoder-tui/package.json` 添加官方 Ink 依赖
2. 新建 `aicoder-tui/src/official-ink/`
3. 新建 `index.tsx`、`App.tsx`、`MainLayout.tsx`
4. 修改主入口，加 `AICODER_TUI_RUNTIME=official-ink` 分支
5. 新建 `useOfficialBackend.ts`，复用现有 RPC
6. 新建 `StatusBar.tsx`
7. 新建 `InputBox.tsx`
8. 新建 `ChatView.tsx`
9. 新建 `ToolCallCard.tsx`
10. 新建 `ApprovalPanel.tsx`
11. 手工跑通聊天
12. 手工跑通工具调用
13. 手工跑通审批
14. 再实现 SlashCommandMenu
15. 新 TUI 稳定后设为默认

---

## 23. 不要在第一阶段做的事

第一阶段不要：

1. 删除 `aicoder-tui/src/ink/`
2. 重写 RPC 协议
3. 重写 Zustand store
4. 重写 Python 后端
5. 做复杂滚动虚拟列表
6. 做复杂主题系统
7. 接入 LangGraph UI 事件

先让官方 Ink 路径可跑通。

---

## 24. 最小可用标准

官方 Ink 改造第一版达到以下标准即可：

1. 能启动
2. 能连接后端
3. 能输入消息
4. 能显示流式回复
5. 能显示工具调用和结果
6. 能审批
7. 能显示当前模式和模型
8. 旧 TUI 可回退

---

## 25. 最终建议

当前项目最优 TUI 改造策略是：

```text
不要在旧自研 renderer 上继续堆复杂功能。
新建 official Ink 路径，复用 RPC/store，逐步替换 UI。
```

这样既能保住现有功能，又能降低后续做 Claude Code 风格交互的成本。
