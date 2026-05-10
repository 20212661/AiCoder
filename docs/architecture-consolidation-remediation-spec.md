# AiCoder 架构收口修复说明书

## 1. 文档目的

本文档用于指导另一个 AI 或开发者完成 AiCoder 当前最重要的三项架构修复工作：

1. 后端旧 `Coder` 抽象与新 `AgentRuntime` 双轨并存的问题
2. 前端 `official-ink` 与 `legacy ink` 双运行时并存的问题
3. 系统提示词、模式语义、权限规则分散导致的行为漂移问题

本文档不是“建议清单”，而是“可执行的修复规格”。执行方应严格按本文档实施，并在完成后提交可验证结果。

---

## 2. 总体目标

### 2.1 目标

将 AiCoder 收敛为一套明确、稳定、可维护的主路径：

- 后端唯一主链：`Coder` 仅作为状态容器，实际对话执行统一走 `AgentRuntime + LangGraph`
- 前端唯一主链：默认且唯一受支持的运行时为 `official-ink`
- 行为唯一事实源：模式、权限、系统提示词的语义由统一模块生成，避免多处重复拼装

### 2.2 完成后的目标状态

- 用户无论从 CLI 还是 `--serve` 进入，都只走统一运行时
- 前端所有核心功能只实现一套，不再双份维护
- `sniff / plan / act` 的行为边界在代码、提示词、RPC 状态、UI 文案中完全一致
- 文档、测试、代码路径三者一致

### 2.3 非目标

本次修复不包含以下内容：

- 不新增新的 Agent 能力
- 不新增新的工具类型
- 不重做 UI 视觉设计
- 不替换 LangGraph、litellm、Ink 等基础框架
- 不处理与本次收口无关的个别功能优化

---

## 3. 背景问题

### 3.1 问题一：后端双轨模型未收口

当前代码中，`AgentRuntime` 已经成为实际主链，但 `base_coder.py` 中仍保留旧的 `whole / diff / ask / architect` 编辑格式入口和旧运行时残留逻辑。

风险：

- 维护者无法快速判断“真实主链”在哪里
- 新功能可能错误加到旧路径
- 测试可能只覆盖主路径，旧路径继续腐烂
- 文档与代码执行现实不一致

### 3.2 问题二：前端双运行时并存

当前 `aicoder-tui/src/index.tsx` 仍保留：

- `official-ink`
- `legacy` 自定义 Ink 路径

同时聊天组件、模型选择器、计划块、命令菜单等存在重复实现。

风险：

- 一个功能要改两遍
- 一个 bug 要修两遍
- 状态、键位、布局、协议事件容易在两条 UI 线发生偏差
- 后续任何 TUI 迭代成本持续上升

### 3.3 问题三：系统提示词与模式语义复杂且分散

当前模式语义涉及多个位置：

- `aicoder/tools/system_prompt.py`
- `aicoder/coders/message_builder.py`
- `aicoder/permission_modes.py`
- `aicoder/tools/executor.py`
- TUI 状态显示与文案
- README 与设计文档

风险：

- 提示词说“允许”，代码层却“拒绝”
- UI 显示模式状态与真实权限不一致
- 新增模式文案时忘记同步权限与测试

---

## 4. 实施原则

执行方必须遵守以下原则：

1. 优先删除重复路径，而不是继续兼容
2. 优先建立单一事实源，而不是在多个模块同步复制逻辑
3. 每个阶段都必须补测试，不允许只改代码不补验收
4. 先收口架构，再做体验优化
5. 如果遇到旧路径仍被调用，必须继续向上追踪并消除入口，而不是只在局部打补丁

---

## 5. 里程碑拆分

本次修复拆分为三个主里程碑和一个收尾里程碑：

1. M1：后端运行时收口
2. M2：前端运行时收口
3. M3：模式语义与提示词统一
4. M4：测试、文档、回归验证收尾

---

## 6. M1：后端运行时收口

## 6.1 目标

让后端只保留一条正式执行路径：

- `Coder` 负责状态、工具注册、会话、repo、命令
- `AgentRuntime` 负责用户一轮对话执行
- `graph/*` 负责状态机节点和路由

旧 `Coder` 主循环只能作为临时兼容层，最终应从默认路径彻底退出。

## 6.2 涉及文件

- `aicoder/coders/base_coder.py`
- `aicoder/agent_runtime.py`
- `aicoder/graph/workflow.py`
- `aicoder/graph/nodes.py`
- `aicoder/coders/ask_coder.py`
- `aicoder/coders/editblock_coder.py`
- `aicoder/coders/wholefile_coder.py`
- `aicoder/coders/architect_coder.py`
- `aicoder/main.py`
- `aicoder/tests/test_coder_init.py`
- `aicoder/tests/test_agent_runtime.py`
- `aicoder/tests/test_graph_workflow.py`

## 6.3 必做改动

### 任务 M1-1：明确运行时主入口

要求：

- `Coder.run()` 或等价入口必须无条件委托给 `AgentRuntime`
- 不允许再通过环境变量、编辑格式、隐藏开关切回旧主循环
- 如果仍保留旧主循环代码，必须标注为 deprecated internal only，且不能被默认流程调用

完成定义：

- 搜索仓库后，不存在任何默认执行路径绕开 `AgentRuntime.run_user_turn()`

### 任务 M1-2：收敛 `edit_format` 的职责

要求：

- 保留 `edit_format` 仅用于提示兼容、模型偏好或少量后处理时，必须明确说明
- 不允许 `edit_format` 再决定“主循环实现”
- 如果 `whole/diff/ask/architect` 只是历史概念，应降级为兼容别名或完全移除

建议策略：

- 短期：保留 CLI 参数，但让其不再决定运行时分支
- 中期：将其文档标注为 legacy compatibility
- 长期：移除或替换为更真实的能力开关

### 任务 M1-3：清理旧循环残骸

要求：

- 检查并处理以下旧逻辑：
  - `_send_message_inner()`
  - `_process_tool_calls()`
  - 旧的 summarization 流程
  - 旧的 context trimming 流程
  - 旧 debug stderr 残留
- 能迁移到 `graph/nodes.py` 的迁移过去
- 不能迁移但必须保留的，写明保留原因

完成定义：

- 旧主循环代码要么被删除，要么明确变成不可达兼容层

### 任务 M1-4：统一运行时状态收尾

要求：

- `done_messages`、`cur_messages`、session 保存、auto-commit 等收尾行为只能有一套正式逻辑
- `AgentRuntime._finalize_coder()` 与其他位置不能重复做同类提交
- 检查异常分支和中断恢复分支是否也能正确收尾

### 任务 M1-5：统一 plan / act / sniff 进入方式

要求：

- 运行模式只由 `tool_exec_state.mode` 或统一状态源控制
- 不允许不同入口对模式含义有不同解释
- `main.py`、`commands.py`、`rpc_io.py`、graph state 应保持一致

## 6.4 验收标准

- CLI 对话路径统一走 `AgentRuntime`
- `--serve` 路径统一走 `AgentRuntime`
- `plan` 模式不会调用编辑工具
- `act` 模式可以调用工具并完成循环
- 中断恢复流程可继续执行，不会丢 session

## 6.5 必跑验证

执行方完成后必须至少跑：

```powershell
pytest aicoder/tests/test_agent_runtime.py
pytest aicoder/tests/test_graph_workflow.py
pytest aicoder/tests/test_graph_act.py
pytest aicoder/tests/test_graph_permissions.py
pytest aicoder/tests/test_coder_init.py
pytest aicoder/tests/test_rpc_e2e.py
```

---

## 7. M2：前端运行时收口

## 7.1 目标

让 `official-ink` 成为唯一正式运行时，避免双份 UI 实现长期共存。

## 7.2 涉及文件

- `aicoder-tui/src/index.tsx`
- `aicoder-tui/src/App.tsx`
- `aicoder-tui/src/official-ink/**`
- `aicoder-tui/src/ink/**`
- `aicoder-tui/src/components/**`
- `aicoder-tui/src/hooks/useBackend.ts`
- `aicoder-tui/src/official-ink/hooks/useOfficialBackend.ts`
- `aicoder-tui/src/stores/**`
- `aicoder-tui/package.json`

## 7.3 必做改动

### 任务 M2-1：确定唯一运行时

要求：

- `src/index.tsx` 默认只启动 `official-ink`
- 移除 `AICODER_TUI_RUNTIME=legacy` 作为正式支持入口
- 如果需要过渡，可保留临时 fallback，但必须：
  - 非默认
  - 文档标记 deprecated
  - 指定删除期限

推荐最终状态：

- 删除 legacy 分流逻辑
- 只保留一个根入口

### 任务 M2-2：组件去重

重点检查是否重复实现：

- `ModelPicker`
- `PlanBlock`
- `SlashCommandMenu`
- `ApprovalPanel`
- `ChatView`
- `MessageBlock`
- `StatusBar`

要求：

- 每类组件只能有一份正式实现
- 若存在“shared”逻辑，提取到公共目录
- 若某份实现仅为 legacy 服务，应删除

### 任务 M2-3：后端连接逻辑去重

当前高风险重复：

- `useBackend`
- `useOfficialBackend`

要求：

- 统一为一个 backend hook
- 它负责：
  - 建连
  - 断连
  - RPC 事件订阅
  - 审批事件分发
  - 状态同步
- 其他 UI 层只消费状态，不重复管理 transport 生命周期

### 任务 M2-4：状态源收口

要求：

- `chatStore / approvalStore / configStore` 为唯一状态事实源
- 运行时组件不能额外持有另一套“长期状态”
- 避免 official/legacy 分别维护自己的连接状态、模式状态、审批队列

### 任务 M2-5：脚本与文档同步

要求：

- `package.json` 中关于 `dev:legacy`、`start:legacy` 的脚本若仍保留，必须标注 deprecated
- 如果已经完成收口，应直接删除 legacy 脚本
- README 与 docs 必须同步更新为“唯一运行时”

## 7.4 验收标准

- 启动 TUI 时只存在一套受支持 UI 路径
- 模型选择、计划块、审批面板、消息渲染等核心能力只维护一套组件
- backend hook 只有一套
- 删除 legacy 后，typecheck 和 build 仍通过

## 7.5 必跑验证

```powershell
cd aicoder-tui
npm run typecheck
npm run build
npm run test
```

如果存在手动冒烟流程，也必须记录：

1. 启动 TUI
2. 发送普通消息
3. 切换 `/plan`
4. 切换 `/act`
5. 触发审批
6. 切换模型
7. 断开后重连或退出

---

## 8. M3：模式语义、权限、提示词统一

## 8.1 目标

建立单一事实源，使以下内容严格一致：

- `sniff / plan / act` 的模式定义
- 工具可见性
- 工具可执行性
- shell 命令限制
- UI 中的模式文案
- system prompt 中的模式说明

## 8.2 涉及文件

- `aicoder/permission_modes.py`
- `aicoder/tools/system_prompt.py`
- `aicoder/coders/message_builder.py`
- `aicoder/tools/executor.py`
- `aicoder/approval.py`
- `aicoder/rpc_io.py`
- `aicoder-tui/src/rpc/protocol.ts`
- `aicoder-tui/src/stores/configStore.ts`
- `aicoder-tui/src/components/**`
- `README.md`
- `aicoder/docs/permission-matrix.md`

## 8.3 必做改动

### 任务 M3-1：定义模式规范源

必须建立一个统一的模式定义层，至少包括：

- mode 名称
- mode 描述
- 可见工具
- 可执行工具
- shell 允许策略
- 用户提示文案摘要

推荐做法：

- 将模式元数据集中在一个模块中
- `permission_modes.py` 和 `system_prompt.py` 都从这一份定义派生

禁止做法：

- 在 `system_prompt.py` 手写一套模式说明
- 在 `permission_modes.py` 再写另一套规则
- 在 UI 中再手写第三套文案

### 任务 M3-2：统一工具可见性与可执行性

要求：

- “提示词里可见” 与 “代码里可执行” 必须一致
- 如果某工具在 `plan` 不可执行，它不应被 prompt 当作可用工具鼓励调用
- 如果某工具在 `sniff` 可见，UI 和 prompt 都应一致展示为侦察工具

### 任务 M3-3：统一 shell 命令规则

要求：

- `approval.py` 的 safe command
- `permission_modes.py` 的只读 shell 允许规则
- `tools/executor.py` 的 auto-approve 逻辑

三处必须对齐。

执行方式：

- 列出所有 shell 判定入口
- 消灭重复分类逻辑
- 保留一个主判断函数

### 任务 M3-4：压缩 system prompt 的职责

要求：

- `system_prompt.py` 只负责“表达规则”，不负责私自发明新规则
- 真实权限规则由代码控制
- prompt 中关于模式的段落必须来自统一模式定义的派生文本

### 任务 M3-5：统一运行时状态文案

要求：

- 模型、模式、phase、yolo 状态的 UI 显示与后端 ready/status 更新一致
- `rpc/protocol.ts` 中的状态字段定义与后端通知一致
- 文案不要出现“Plan Mode”与“read-only mode”说法混乱的情况

## 8.4 验收标准

- 同一个模式在代码、提示词、UI、文档中没有冲突描述
- 添加一个新模式字段时，只需改一处定义，其余自动派生或最小同步
- shell 权限规则可以通过测试明确验证

## 8.5 必跑验证

```powershell
pytest aicoder/tests/test_permission_modes.py
pytest aicoder/tests/test_system_prompt.py
pytest aicoder/tests/test_approval.py
pytest aicoder/tests/test_commands.py
pytest aicoder/tests/test_rpc_io.py
```

---

## 9. M4：文档、测试、回归收尾

## 9.1 目标

确保“代码现实”与“项目说明”一致，避免收口完成后又被误导回旧路径。

## 9.2 必做改动

### 任务 M4-1：更新 README

README 必须明确写清：

- 后端唯一主链是 `AgentRuntime + LangGraph`
- TUI 唯一正式运行时是 `official-ink`
- `whole/diff/ask/architect` 的现状
- `sniff / plan / act` 的真实语义

### 任务 M4-2：更新架构文档

至少同步更新：

- `aicoder/docs/runtime-unification.md`
- `aicoder/docs/permission-matrix.md`
- `docs/rpc-protocol.md`

### 任务 M4-3：回归测试清单

执行方完成后必须提交一份回归说明，至少覆盖：

1. CLI 普通消息
2. CLI `/plan`
3. CLI `/act`
4. CLI `/sniff`
5. TUI 启动
6. TUI 发送消息
7. TUI 审批
8. TUI 模型切换
9. `--serve` 启动和 round trip

---

## 10. 最终交付要求

执行方交付时必须提供以下内容：

### 10.1 代码交付

- 所有改动文件列表
- 删除了哪些 legacy 入口
- 保留了哪些兼容层以及原因

### 10.2 测试交付

- 实际执行过的命令
- 通过结果
- 若有跳过项，必须说明原因

### 10.3 说明交付

- 本次收口后的唯一主链说明
- 仍未解决的遗留问题列表
- 下一阶段建议，但不能把本次未完成工作伪装成“后续优化”

---

## 11. AI 执行限制

交给另一个 AI 执行时，必须附带以下约束：

1. 不要只写方案，必须实际改代码
2. 不要保留“以后再删”的双份实现，除非文档明确允许临时兼容
3. 不要新增第三套抽象层
4. 不要通过增加配置开关来回避收口
5. 删除 legacy 代码前，先确认无测试依赖
6. 每完成一个里程碑，就补对应测试与文档

---

## 12. 建议执行顺序

严格按以下顺序执行：

1. 先完成 M1 后端运行时收口
2. 再完成 M2 前端运行时收口
3. 再完成 M3 模式语义与提示词统一
4. 最后完成 M4 文档与回归收尾

原因：

- 后端主链不收口，前端很难真正稳定
- 前端不收口，模式状态在 UI 上仍会漂移
- 规则不统一，后续任何新功能都会继续扩大技术债

---

## 13. 验收口径

我后续验收时将重点检查以下内容：

1. 是否真的删掉或封死了旧运行路径，而不是换了个名字继续保留
2. 是否真的只剩一套前端运行时，而不是把 legacy 藏起来
3. 模式、权限、提示词是否已经由统一定义派生
4. README、测试、代码是否一致
5. 是否提供了实际跑过的验证结果

如果以上任一项不满足，我会判定为“未完成收口，只做了局部整理”。
