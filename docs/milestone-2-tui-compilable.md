# 里程碑 2：TUI 工程可编译

## 目标

让 `aicoder-tui` 从“迁移中、不可稳定维护”收敛到“至少可以 typecheck，可持续修复和演进”的状态。

本里程碑完成后，应达到以下状态：

- `aicoder-tui` 能通过 `npm run typecheck`
- 主要技术路线清晰，不再混杂大量无主迁移残留
- Node/TypeScript 默认开发链路可维护
- 前后端 RPC 边界更容易联调

## 背景问题

当前 TUI 存在这些典型问题：

- 大量 TypeScript 报错
- `react/compiler-runtime` 相关代码未稳定接入
- 存在 Bun 运行时假设
- 部分模块路径失效或文件缺失
- 迁移残留代码较多，维护边界不清晰

## 本里程碑范围

要做：

- 系统分类 typecheck 错误
- 优先修迁移残留和引用错误 
- 收敛 Bun / compiler-runtime 依赖
- 整理 RPC 协议边界

不做：

- 完整视觉重设计
- 复杂交互能力扩展
- 大规模重写自定义 Ink 体系

## AI 执行总要求

请按以下原则执行：

1. 先让工程可维护，再追求高级优化。
2. 优先删除无主依赖链，而不是到处堆 `any`。
3. 不要把未来路线写成当前完成状态。
4. 每做一批修改都要重新跑 `npm run typecheck`。
5. 若发现某一块迁移代码明显未接入主入口，可先隔离或删除，但要说明依据。

---

## 任务 1：建立 TUI 错误分类清单

### 目标

先把错误分组，而不是无序修复。

### 需要阅读

- `aicoder-tui/tsconfig.json`
- `aicoder-tui/package.json`
- `npm run typecheck` 报错输出

### 需要执行

1. 运行：
   - `npm run typecheck`
2. 将错误按以下类别分类：
   - 错误 import/export
   - 缺失文件/路径
   - `react/compiler-runtime`
   - Bun 假设
   - JSX intrinsic element 类型缺失
   - 第三方声明缺失
   - 纯类型标注缺失
3. 生成文档：
   - `aicoder-tui/docs/typecheck-triage.md`

### 验收标准

- 能明确指出“先修什么、后修什么”
- 不再以报错顺序作为修复顺序

---

## 任务 2：修复第一批迁移残留错误

### 目标

优先降低“明显是迁移残留”的错误数量。

### 需要阅读

- `aicoder-tui/src/hooks/useBackend.ts`
- `aicoder-tui/src/utils/*`
- `aicoder-tui/src/ink/components/*`
- `aicoder-tui/src/design-system/*`
- 其他被 triage 文档标记为高优先级的问题文件

### 需要执行

优先修：

- 无定义符号
- 错误 export/import
- 指向不存在文件的引用
- 明显拼写错误的方法

重点关注：

- `debugLog`
- `checkProtectedNamespace`
- `truncate.js`
- `markdown.ts` 里的失效依赖

### 验收标准

- typecheck 报错显著下降
- 清理掉一批无主迁移残留

---

## 任务 3：收敛 Bun 运行时假设

### 目标

让默认开发环境不依赖 Bun 类型和 Bun 专属能力。

### 需要阅读

- `aicoder-tui/src/utils/hash.ts`
- `aicoder-tui/src/utils/env.ts`
- `aicoder-tui/src/ink/utils/semver.ts`
- `aicoder-tui/src/ink/stringWidth.ts`
- `aicoder-tui/src/ink/wrapAnsi.ts`

### 需要执行

1. 判断 Bun 相关逻辑哪些只是性能优化。
2. 保留可选优化分支，但不能让默认 Node 开发流程报错。
3. 必要时：
   - 改为运行时判断
   - 加最小兼容声明
   - 回退到普通 Node 可维护实现

### 验收标准

- Bun 不再是 typecheck 的硬依赖
- 技术路线更适合普通 Node 开发环境

---

## 任务 4：处理 `react/compiler-runtime` 相关问题

### 目标

决定并收敛这条技术路线，避免其成为长期阻塞项。

### 需要阅读

- `aicoder-tui/src/design-system/ThemedBox.tsx`
- `aicoder-tui/src/design-system/ThemedText.tsx`
- `aicoder-tui/src/ink/Ansi.tsx`
- 其他引用 `react/compiler-runtime` 的文件

### 需要执行

1. 判断这些写法是否必须保留。
2. 如果不是必须，优先回退到普通 React/TS 可维护写法。
3. 如果必须保留，则补齐其最小可编译接入方式。
4. 记录这项技术取舍。

### 验收标准

- 不再因为 compiler-runtime 导致大面积类型错误
- 路线选择有明确说明

---

## 任务 5：补齐 JSX 与第三方类型缺口

### 目标

把剩余偏工程层的类型缺口补齐。

### 需要执行

1. 处理自定义 JSX host elements 的类型声明。
2. 补第三方缺失类型的最小声明文件。
3. 修复明显的隐式 `any` 和错误签名问题。
4. 避免用粗暴方式让类型系统失真。

### 验收标准

- 类型问题主要剩余应为真实实现问题，而不是基础声明缺失

---

## 任务 6：整理 RPC 联调面

### 目标

让 TUI 与 Python 后端之间的协议边界更清晰，减少调试噪音。

### 需要阅读

- `aicoder/rpc_io.py`
- `aicoder-tui/src/rpc/protocol.ts`
- `aicoder-tui/src/rpc/methods.ts`
- `aicoder-tui/src/hooks/useBackend.ts`

### 需要执行

1. 对照前后端实际使用的 RPC method。
2. 修正明显不一致的字段名或类型假设。
3. 协助产出协议文档：
   - `aicoder/docs/rpc-protocol.md`
4. 默认减少 stderr 调试噪音。

### 验收标准

- 前后端至少对关键事件的结构认知一致
- 联调时不再被无关调试日志淹没

---

## 任务 7：达成 typecheck 通过

### 目标

让 `aicoder-tui` 进入“可以继续演进”的基本状态。

### 需要执行

1. 反复迭代修复剩余 typecheck 错误。
2. 每轮只解决一类问题，避免混乱改动。
3. 最终运行：
   - `npm run typecheck`
4. 如能顺带通过 `build`，记录为额外收益；如不能，不强行扩范围。

### 验收标准

- `npm run typecheck` 通过
- 或者至少只剩极少数明确、可解释、已记录的阻塞项

---

## 建议执行顺序

1. 建立 TUI 错误分类清单
2. 修复第一批迁移残留错误
3. 收敛 Bun 运行时假设
4. 处理 `react/compiler-runtime` 问题
5. 补齐 JSX 与第三方类型缺口
6. 整理 RPC 联调面
7. 达成 typecheck 通过

---

## 每次执行后的输出格式

请严格按以下格式汇报：

1. 分析
   - 看了哪些文件
   - 当前主要是哪类错误
   - 这轮准备处理什么
2. 实施
   - 改了哪些文件
   - 为什么这么改
3. 验证
   - 运行了什么命令
   - typecheck 报错是否下降
4. 总结
   - 当前还剩几类问题
   - 下轮最该处理哪一类
