# 移除 `/shit` Persona 完整规划

本文档用于指导 AI 在当前 `AiCoder` 项目中**完整移除 SHIT persona 模式**。目标是删除 `/shit` 及其相关人格、主题、命令、提示词和文档残留，同时**保留已经独立成型的 `sniff / plan / act` 三态模式**，不破坏现有统一 runtime、权限链、工具链和 TUI 主流程。

本文档是“执行规划”，不是实现报告。执行时应严格按本文档顺序推进，并在每一步后做验证。

---

## 1. 目标

移除以下能力与概念：

- `persona = "shit"`
- `persona_submode = "excrete" | "chaos"`
- CLI 参数：`--persona shit`、`--shit`
- 命令：`/shit`、`/excrete`、`/chaos`、`/blind`、`/eyes`
- SHIT 专属系统提示词
- SHIT 审批文案前缀
- SHIT TUI 主题与状态标签
- SHIT 相关测试与文档

移除后保留：

- `mode = "sniff" | "plan" | "act"`
- `/sniff`、`/plan`、`/act`
- 普通审批链
- 普通主题
- RPC / TUI / graph / runtime 的正常运行

---

## 2. 非目标

本次不做以下事情：

- 不重构 `sniff` 模式本身
- 不重写权限模型
- 不新增新的 persona 机制替代 SHIT
- 不大改 TUI 布局
- 不修改现有工具系统语义

---

## 3. 执行原则

执行过程中必须遵守：

1. 先删入口，再删实现，再删状态字段，最后删文档和测试残留。
2. 不允许只删 UI 文案而保留后端状态字段。
3. 不允许只删命令而保留 CLI 参数、RPC 字段或 theme 分支。
4. 保证 `sniff / plan / act` 三种模式在删除后仍语义清晰。
5. 删除后不得留下无用字段、无用 import、无用测试、无用 docs 链接。

---

## 4. 当前影响面

根据当前代码，SHIT persona 影响以下区域。

### 4.1 后端入口与状态

- `aicoder/main.py`
- `aicoder/coders/base_coder.py`
- `aicoder/agent_runtime.py`
- `aicoder/graph/state.py`
- `aicoder/rpc_io.py`

### 4.2 命令系统

- `aicoder/commands.py`

### 4.3 人格与提示词

- `aicoder/personas/__init__.py`
- `aicoder/personas/shit.py`
- `aicoder/tools/system_prompt.py`
- `aicoder/tools/system_prompt_shit.py`

### 4.4 审批系统

- `aicoder/approval.py`

### 4.5 TUI 展示与协议

- `aicoder-tui/src/rpc/protocol.ts`
- `aicoder-tui/src/stores/configStore.ts`
- `aicoder-tui/src/official-ink/theme.ts`
- `aicoder-tui/src/official-ink/components/StatusBar.tsx`
- `aicoder-tui/src/official-ink/components/InputBox.tsx`
- `aicoder-tui/src/official-ink/components/SlashCommandMenu.tsx`

### 4.6 测试

- `aicoder/tests/test_commands.py`
- `aicoder/tests/test_approval.py`
- `aicoder/tests/test_agent_runtime.py`
- `aicoder/tests/test_graph_state.py`

### 4.7 文档

- `docs/shit-persona-implementation-plan.md`
- `docs/shit-persona-post-review-fixes.md`
- `docs/sniff-mode-design.md`
- `docs/sniff-mode-implementation-plan.md`
- 其他出现 SHIT 描述的 README 或说明文档

---

## 5. 建议执行顺序

建议分 6 个阶段执行。

### 阶段 1：移除外部入口

目标：让新用户无法再进入 SHIT persona。

要做的事：

1. 从 CLI 参数中移除：
   - `--persona`
   - `--shit`
   或者至少移除 `shit` 选项，仅保留默认普通模式
2. 从 slash 命令入口中移除：
   - `/shit`
   - `/excrete`
   - `/chaos`
   - `/blind`
   - `/eyes`
3. 更新 `/help` 和命令菜单，确保这些命令不再对外可见

涉及文件：

- `aicoder/main.py`
- `aicoder/commands.py`
- `aicoder-tui/src/official-ink/components/InputBox.tsx`
- `aicoder-tui/src/official-ink/components/SlashCommandMenu.tsx`

验收标准：

- CLI 帮助里不再出现 SHIT 参数
- `/help` 不再列出 SHIT 命令
- slash 命令菜单不再列出 SHIT 命令

---

### 阶段 2：移除后端 persona 状态

目标：让 runtime、graph、coder 不再携带无用人格字段。

要做的事：

1. 从 `Coder` 构造参数中删除：
   - `persona`
   - `persona_submode`
2. 删除 `self.persona`、`self.persona_submode` 及其透传逻辑
3. 从 `AgentRuntime._initial_state()` 中删除：
   - `persona`
   - `persona_submode`
4. 从 `AgentGraphState` 中删除：
   - `Persona`
   - `PersonaSubMode`
   - `persona`
   - `persona_submode`
5. 从 RPC 状态广播中删除：
   - `persona`
   - `personaSubMode`

涉及文件：

- `aicoder/coders/base_coder.py`
- `aicoder/agent_runtime.py`
- `aicoder/graph/state.py`
- `aicoder/rpc_io.py`
- `aicoder/main.py`

验收标准：

- graph state 不再声明 persona 字段
- runtime 初始化状态不再包含 persona 字段
- RPC payload 不再广播 persona 字段

---

### 阶段 3：移除 persona 实现与提示词分支

目标：彻底删掉 SHIT 逻辑源头。

要做的事：

1. 删除 `aicoder/personas/shit.py`
2. 精简 `aicoder/personas/__init__.py`
3. 删除 `aicoder/tools/system_prompt_shit.py`
4. 在 `aicoder/tools/system_prompt.py` 中：
   - 删除 `persona` / `persona_submode` 配置参数
   - 删除 `if self._persona == "shit"` 分支
   - 收口到单一普通系统提示词路径

涉及文件：

- `aicoder/personas/shit.py`
- `aicoder/personas/__init__.py`
- `aicoder/tools/system_prompt.py`
- `aicoder/tools/system_prompt_shit.py`

验收标准：

- 代码中不再 import `build_shit_system_prompt`
- 不再存在 `personas/shit.py`
- SystemPrompt 不再依赖 persona 分支

---

### 阶段 4：移除审批文案和 TUI 主题分支

目标：清掉所有 persona 驱动的展示层分叉。

要做的事：

1. 在 `approval.py` 中删除：
   - `set_persona()`
   - `format_approval_title()` 中 SHIT 前缀分支
   - 任何 `self.persona == "shit"` 判断
2. 在 TUI 中删除：
   - `shitTheme`
   - `persona === "shit"` 的颜色分支
   - `SHIT` 状态标签
   - `#` 输入提示符
3. 将状态栏、输入框、菜单统一回普通主题逻辑

涉及文件：

- `aicoder/approval.py`
- `aicoder-tui/src/official-ink/theme.ts`
- `aicoder-tui/src/official-ink/components/StatusBar.tsx`
- `aicoder-tui/src/official-ink/components/InputBox.tsx`
- `aicoder-tui/src/official-ink/components/SlashCommandMenu.tsx`

验收标准：

- TUI 不再 import `shitTheme`
- 状态栏不再显示 `SHIT`
- 输入前缀统一回 `>`
- 审批标题不再出现 SHIT 文案

---

### 阶段 5：收口协议与 store 类型

目标：删掉协议和状态管理中的 persona 类型残留。

要做的事：

1. 从 RPC 协议中删除：
   - `persona?: "normal" | "shit"`
   - `personaSubMode`
2. 从前端 store 中删除：
   - `persona`
   - persona 相关 setter / update 分支
3. 检查后端与前端所有状态同步路径，确保不存在未使用字段

涉及文件：

- `aicoder-tui/src/rpc/protocol.ts`
- `aicoder-tui/src/stores/configStore.ts`
- `aicoder/rpc_io.py`

验收标准：

- 前端类型定义中不再出现 `shit`
- `useConfigStore` 不再保存 persona
- 后端与前端协议字段一致

---

### 阶段 6：删除测试与文档残留

目标：让仓库不再声称支持 SHIT persona。

要做的事：

1. 删除或改写所有 SHIT 专属测试
2. 保留与 `sniff` 独立 mode 相关的测试
3. 处理 docs：
   - 删除专门描述 SHIT persona 的文档
   - 或在不想删文件时，至少明确标记为“已废弃”
4. 更新任何仍提到 SHIT persona 的帮助文本或架构说明

涉及文件：

- `aicoder/tests/test_commands.py`
- `aicoder/tests/test_approval.py`
- `aicoder/tests/test_agent_runtime.py`
- `aicoder/tests/test_graph_state.py`
- `docs/shit-persona-implementation-plan.md`
- `docs/shit-persona-post-review-fixes.md`
- `docs/sniff-mode-design.md`
- `docs/sniff-mode-implementation-plan.md`

验收标准：

- 仓库内不再有面向用户的 SHIT persona 文档
- 测试中不再断言 `persona == "shit"`
- `sniff` 设计文档不再把 SHIT persona 作为前提

---

## 6. 具体改动建议

### 6.1 `aicoder/main.py`

建议改动：

- 移除 `--shit`
- 若 `--persona` 仅为 SHIT 引入，则整体删除
- 删除参数解析后对 `persona = "shit"` 的特殊赋值

注意：

- 如果 `main.py` 有 session 恢复或 `SwitchCoder` 传参逻辑，也要同步删掉 `persona_submode`

---

### 6.2 `aicoder/coders/base_coder.py`

建议改动：

- 删掉构造函数中的 `persona`、`persona_submode`
- 删掉实例字段
- 删掉任何 `kwargs.setdefault("persona_submode", ...)`
- 收口 `_update_tool_model_info()` 的参数透传

---

### 6.3 `aicoder/commands.py`

建议改动：

- 删除：
  - `cmd_shit`
  - `cmd_excrete`
  - `cmd_chaos`
  - `cmd_blind`
  - `cmd_eyes`
- 保留：
  - `cmd_sniff`
  - `cmd_plan`
  - `cmd_act`
  - `cmd_yolo`

注意：

- 如果 `/blind` / `/eyes` 只是 `/yolo` 的文案别名，直接删即可，不需要保留兼容层

---

### 6.4 `aicoder/tools/system_prompt.py`

建议改动：

- `configure()` 只保留真正需要的参数
- 删除 `_persona`、`_persona_submode`
- `build()` 中只走普通提示词路径

同时建议顺手优化：

- 现在 `SNIFF MODE` / `PLAN MODE` / `ACT MODE` 已经是正式结构
- 可以继续把提示词文案统一为三态模式描述，避免历史措辞残留

---

### 6.5 `aicoder/approval.py`

建议改动：

- 删除 persona 存储
- 删除 `format_approval_title()` 中 SHIT 前缀逻辑
- 保留普通审批标题生成逻辑

---

### 6.6 TUI

建议改动：

- `theme.ts` 删除 `shitTheme`
- `StatusBar.tsx` 删除 persona 分支与 `SHIT` 标签
- `InputBox.tsx` 删除 persona 分支与 SHIT help 文案
- `SlashCommandMenu.tsx` 删除 SHIT 命令项与 persona 主题分支
- `configStore.ts` 删除 persona 字段与协议映射

注意：

- 现在 `mode === "sniff" || mode === "plan"` 的只读判断要保留
- 不要误删和 `sniff` 相关的逻辑

---

## 7. 测试调整建议

### 7.1 应删除或改写的测试

应删除或重写以下类别：

- `/shit` 命令行为测试
- `/excrete`、`/chaos`、`/blind`、`/eyes` 测试
- approval 标题 SHIT 前缀测试
- graph state 中 `persona/persona_submode` 字段测试
- runtime 初始化中 persona 字段测试

### 7.2 必须保留并确保通过的测试

重点保留：

- `sniff` mode 权限测试
- `plan` / `act` mode 测试
- `/sniff`、`/plan`、`/act` 命令测试
- RPC / TUI E2E 测试
- typecheck / build

---

## 8. 建议验证命令

后端：

```powershell
pytest
```

前端：

```powershell
cd aicoder-tui
cmd /c npm run typecheck
cmd /c npm run build
```

全文残留检查：

```powershell
rg -n "shit|persona_submode|/shit|/excrete|/chaos|/blind|/eyes|shitTheme|SHIT" aicoder aicoder-tui docs
```

最终验收时，`rg` 结果应只剩：

- 本移除规划文档本身
- 如保留的废弃说明文档中的“已废弃”文字

不应再出现在运行时代码和用户可见帮助文本中。

---

## 9. 推荐交付顺序

推荐 AI 实施顺序：

1. 先删 CLI / slash 命令入口
2. 再删后端状态字段
3. 再删 prompt / personas / approval 分支
4. 再删 TUI 主题和协议
5. 再删测试
6. 最后删或标记废弃 docs
7. 跑全量验证
8. 用 `rg` 做一次全文残留检查

---

## 10. 完成定义

当且仅当以下条件全部满足，才算移除完成：

1. 用户无法再通过 CLI 或 slash command 启用 SHIT persona
2. 运行时代码不再包含 `persona == "shit"` 分支
3. graph / runtime / RPC / store 中不再包含 persona 残留字段
4. TUI 不再展示 SHIT 主题、标签或命令
5. 测试全绿
6. `typecheck` 和 `build` 通过
7. 代码库中不再有运行时代码引用 `shitTheme`、`system_prompt_shit.py` 或 `personas/shit.py`

---

## 11. 可直接交给 AI 的执行提示词

```text
请根据 docs/remove-shit-persona-plan.md 执行 SHIT persona 移除工作。

要求：
1. 先阅读文档和相关代码，再实施修改。
2. 按文档中的阶段顺序执行，不要跳步。
3. 删除 `/shit`、`/excrete`、`/chaos`、`/blind`、`/eyes` 及其所有运行时残留。
4. 保留并确保 `sniff / plan / act` 三态模式继续正常工作。
5. 删除 persona / persona_submode / shitTheme / SHIT prompt / SHIT approval 文案分支。
6. 同步更新测试和文档，避免留下死代码或死文档。
7. 最后运行：
   - pytest
   - aicoder-tui 下的 npm run typecheck
   - aicoder-tui 下的 npm run build
   - rg -n "shit|persona_submode|/shit|/excrete|/chaos|/blind|/eyes|shitTheme|SHIT" aicoder aicoder-tui docs
8. 输出：
   - 改了哪些文件
   - 删掉了哪些能力
   - 验证结果
   - 是否还有残留
```

