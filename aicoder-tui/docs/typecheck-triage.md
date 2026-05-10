# Typecheck 错误分类清单

生成时间: 2026-05-09
总错误数: 145 / 涉及文件: 37

## 错误分类统计

| 优先级 | 类别 | 错误码 | 数量 | 文件数 |
|--------|------|--------|------|--------|
| P0 | react/compiler-runtime 残留 | TS2305 | 14 | 14 |
| P0 | compiler-runtime 导致的隐式 any | TS7006 | 30 | 14 |
| P1 | Bun 运行时假设 | TS2868 | 23 | 4 |
| P1 | 缺失第三方类型声明 | TS7016 | 18 | 8 |
| P2 | JSX IntrinsicElements 缺失 | TS2339 | ~10 | 6 |
| P2 | 缺失文件/模块引用 | TS2307 | 7 | 3 |
| P3 | 未使用的 @ts-expect-error | TS2578 | 11 | 2 |
| P3 | osc.ts API 调用错误 | TS2554+TS2339 | ~12 | 1 |
| P3 | 错误 import 方式 | TS2614 | 3 | 2 |
| P3 | 未定义符号 | TS2304 | 2 | 1 |
| P4 | 其他杂项 | TS2322/2345/2367/2551/7053/7034/7005 | 8 | 5 |

## 修复优先级与策略

### P0: react/compiler-runtime 残留（~44 errors）

**根因**: 代码从 React Compiler 编译输出反编译而来，包含 `import {c} from "react/compiler-runtime"` 及自动生成的参数 `t0` 等。

**涉及文件**:
- `src/design-system/ThemedBox.tsx`, `ThemedText.tsx`
- `src/ink/Ansi.tsx`
- `src/ink/components/AlternateScreen.tsx`, `Box.tsx`, `Button.tsx`, `ClockContext.tsx`, `Link.tsx`, `Newline.tsx`, `NoSelect.tsx`, `RawAnsi.tsx`, `Spacer.tsx`, `TerminalFocusContext.tsx`, `Text.tsx`

**策略**: 将编译产物回退为普通 React/TypeScript 可维护写法，删除 compiler-runtime 导入，恢复原始组件结构。

### P1: Bun 运行时假设（23 errors）

**根因**: 代码假设运行在 Bun 环境中，直接使用 `Bun.file()`/`Bun.version` 等全局 API。

**涉及文件**:
- `src/utils/hash.ts` (5 errors)
- `src/ink/stringWidth.ts` (3 errors)
- `src/ink/wrapAnsi.ts` (3 errors)
- `src/ink/utils/semver.ts` (14 errors - 含 semver 类型缺失)

**策略**: 改为运行时判断 `typeof Bun !== 'undefined'`，保留可选优化分支，默认回退到 Node 实现。

### P1: 缺失第三方类型声明（18 errors）

**涉及模块**:
- `bidi-js` — 无 @types
- `stack-utils` — 无 @types
- `lodash-es/memoize.js`, `lodash-es/noop.js`, `lodash-es/throttle.js` — 子路径导入
- `react-reconciler`, `react-reconciler/constants.js` — 无内置类型
- `semver` — 有 @types/semver 但未安装

**策略**: 安装 `@types/semver`；其余无 @types 的添加最小 `.d.ts` 声明文件。

### P2: JSX IntrinsicElements 缺失（~10 errors）

**根因**: 自定义 Ink host elements (`ink-box`, `ink-text`, `ink-link`, `ink-raw-ansi`) 未在 JSX 类型中声明。

**策略**: 创建 `src/ink/jsx-types.d.ts` 扩展 `JSX.IntrinsicElements`。

### P2: 缺失文件/模块引用（7 errors）

**涉及**:
- `../../bootstrap/state.js` — ScrollBox.tsx 引用不存在的路径
- `./truncate.js` — format.ts 引用
- `../components/design-system/color.js` — markdown.ts 引用
- `../constants/figures.js` — markdown.ts 引用
- `./cliHighlight.js`, `./hyperlink.js`, `./messages.js` — markdown.ts 引用

**策略**: 检查这些模块是否实际存在于其他路径，修正引用或删除无用导入。

### P3: 未使用的 @ts-expect-error（11 errors）

**涉及文件**: `src/ink/ink.tsx`, `src/ink/render-to-screen.ts`

**策略**: 直接删除这些多余的 `@ts-expect-error` 注释。

### P3: osc.ts API 错误（~12 errors）

**根因**: `String.prototype.code` 不存在；函数调用参数数量不匹配。

**策略**: 修正为正确的 API 调用方式（`charCodeAt` 或 `codePointAt`）。

### P3: 错误 import 方式（3 errors）

**涉及**: `PasteEvent`, `ResizeEvent`, `Cursor` 使用了 named import 但应为 default import。

**策略**: 改为 `import PasteEvent from ...` 形式。

### P3: 未定义符号（2 errors）

**涉及**: `debugLog` 在 App.tsx 中未导入。

**策略**: 检查 debugLog 来源，补充导入或替换为现有日志函数。

## 执行顺序

1. **P0** — compiler-runtime 回退（消除最大错误源）
2. **P1** — Bun 假设收敛 + 第三方声明
3. **P2** — JSX 类型 + 缺失模块
4. **P3** — 杂项修复
5. **验证** — 最终 typecheck 通过
