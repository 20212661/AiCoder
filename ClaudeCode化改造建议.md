# aiCoder 模块取舍与 Claude Code 化改造建议

## 目标

这份文档回答三个问题：

1. 哪些模块值得保留
2. 哪些模块建议重写
3. 哪些模块建议直接照 Claude Code 的思路去抄

核心判断：

- 当前项目不适合全量推倒重写
- 当前项目适合在现有骨架上做一次面向 Claude Code 的架构翻修
- 最应该升级的是权限模式系统、工具运行时、前端交互模型，而不是先换语言

---

## 一、值得保留的模块

这些模块已经形成了基本骨架，继续保留和演进的性价比最高。

### 1. 后端主程序与会话骨架

建议保留：

- `aicoder/main.py`
- `aicoder/session.py`
- `aicoder/history.py`
- `aicoder/context_manager.py`

原因：

- 已经具备 CLI 运行入口和会话基础能力
- 会话、历史、上下文裁剪这类能力无论是不是 Claude Code 路线都需要
- 这些模块不是当前产品“落后感”的主要来源

保留方式：

- 保留文件和职责
- 后续只做结构增强，不建议推翻

### 2. 工具抽象层

建议保留：

- `aicoder/tools/spec.py`
- `aicoder/tools/result.py`
- `aicoder/tools/registry.py`
- `aicoder/tools/parser.py`
- `aicoder/tools/handlers/base.py`

原因：

- 你已经有了工具定义、工具注册、工具结果、工具处理器这些基础抽象
- 这正是 agent runtime 的核心骨架
- 只要继续加强权限语义和执行流，不需要重做整个工具系统

保留方式：

- 保留抽象
- 增强字段和状态
- 让更多决策统一汇总到权限与执行入口

### 3. 基础工具实现

建议保留：

- `aicoder/tools/handlers/read_file_handler.py`
- `aicoder/tools/handlers/search_files_handler.py`
- `aicoder/tools/handlers/list_files_handler.py`
- `aicoder/tools/handlers/edit_file_handler.py`
- `aicoder/tools/handlers/write_file_handler.py`
- `aicoder/tools/handlers/run_shell_handler.py`

原因：

- 这些能力本身就是 AI coding CLI 的基础工具集
- 当前实现虽然不够 Claude Code 化，但功能层已经可用
- 可以逐步升级权限、显示、上下文压缩，而不是重写工具本体

保留方式：

- 工具逻辑保留
- 在权限校验、模式约束、结果摘要、结构化展示上继续改

### 4. RPC 通信层

建议保留：

- `aicoder/rpc_io.py`
- `aicoder-tui/src/rpc/`

原因：

- Python 后端和 TS TUI 之间已经有可工作的边界
- RPC 协议是你后续分层演进的基础
- 即使以后内核迁移，协议层设计也能继续复用

保留方式：

- 保留通信方式
- 扩展事件类型和状态字段
- 不建议现在推翻通信层

### 5. TUI 状态管理基础

建议保留：

- `aicoder-tui/src/stores/chatStore.ts`
- `aicoder-tui/src/stores/configStore.ts`
- `aicoder-tui/src/stores/approvalStore.ts`
- `aicoder-tui/src/hooks/useBackend.ts`

原因：

- 已经具备前端状态与后端事件同步能力
- 这套 store 结构很适合继续承接模式状态、审批流、计划流
- 不需要为了“更先进”立刻推翻前端状态层

保留方式：

- 保留 store 分层
- 增加更强的模式和任务状态字段

### 6. 测试体系

建议保留：

- `aicoder/tests/`

原因：

- 当前测试已经覆盖工具、命令、审批等关键路径
- 这是后续安全重构最重要的护栏
- 真正想向 Claude Code 靠近，必须靠测试锁行为

保留方式：

- 保留现有测试结构
- 以后新增模式状态机、计划流、审批流测试

---

## 二、建议重写的模块

这些模块不是完全不能用，而是当前设计层级偏早期，继续打补丁会越来越别扭，建议逐步重写。

### 1. 工具执行入口

建议重写：

- `aicoder/tools/executor.py`

原因：

- 这是整个 runtime 的心脏
- 当前已经能用，但还不够像 Claude Code 那种“统一权限管道 + 模式驱动 + 工具后处理”
- 以后要支持更多模式、结构化审批、计划提交、工具后处理，执行器需要更清晰的阶段化设计

重写方向：

- 拆成明确阶段：
  - 输入校验
  - 模式权限判断
  - 工具级权限判断
  - 用户审批
  - 执行
  - 后处理
  - UI 摘要
- 把“模式逻辑”和“审批逻辑”从执行器内部进一步抽离

### 2. 审批系统

建议重写：

- `aicoder/approval.py`

原因：

- 当前更像“自动批准配置器”
- Claude Code 那种体验不是简单 allowlist，而是：
  - 模式上下文
  - 工具规则
  - 内容级规则
  - 安全路径规则
  - 结构化请求
- 现在这层还不够统一

重写方向：

- 从“工具类别开关”升级为“权限决策引擎”
- 输出统一决策结构：
  - `allow`
  - `ask`
  - `deny`
  - `reason`
  - `source`

### 3. 命令系统中的模式切换逻辑

建议重写：

- `aicoder/commands.py` 中与 `/plan`、`/act`、审批、模式相关部分

原因：

- 当前 slash command 只是一个入口
- Claude Code 风格不是“用户纯手工切模式”，而是：
  - 用户可切
  - AI 也可进入计划流
  - 模式切换带上下文和 UI 行为变化

重写方向：

- 保留 slash command 入口
- 但不要让模式系统依附在 slash command 上
- 模式系统应该成为独立状态机

### 4. System Prompt 组织方式

建议重写：

- `aicoder/tools/system_prompt.py`

原因：

- 当前 system prompt 还是“静态大段说明书”的味道
- Claude Code 更强的是“基础 system prompt + 动态附件/模式提示/工具可见性”
- 只靠一个大 prompt 文件会越来越难维护

重写方向：

- 拆成：
  - 固定身份与原则
  - 工具说明
  - 模式说明
  - 动态附件
  - 恢复性提示

### 5. TUI 消息呈现层

建议重写：

- `aicoder-tui/src/components/chat/`
- `aicoder-tui/src/components/tools/ToolCallCard.tsx`
- `aicoder-tui/src/components/approval/ApprovalDialog.tsx`

原因：

- 现在还是“聊天 + 工具卡片”
- Claude Code 的感觉来自“工作流型 UI”，不是普通聊天记录

重写方向：

- 强化模式展示
- 强化计划展示
- 强化审批展示
- 强化工具过程反馈

---

## 三、建议直接照 Claude Code 抄的模块与能力

这里不是说逐字抄实现，而是架构和交互思路应该尽量贴近。

### 1. 权限模式系统

优先级：最高

建议直接对标 Claude Code 的模式分层：

- `default`
- `acceptEdits`
- `plan`
- `bypassPermissions`
- 以后再考虑 `dontAsk`
- 以后再考虑 `auto`

当前项目应该先做：

1. 完成 `plan`
2. 新增 `default`
3. 新增 `acceptEdits`
4. 新增 `bypassPermissions`
5. 统一模式循环与 UI 展示

对应位置：

- 新建独立权限模式模块
- 统一从工具执行入口消费
- 前端状态栏与输入区同步展示

### 2. “进入计划模式 / 退出计划模式”专用工具

优先级：最高

这是你现在和 Claude Code 体验差距非常大的地方。

建议直接抄的能力：

- `EnterPlanMode`
- `ExitPlanMode`

要点：

- 不只是用户手动 `/plan`
- 允许 AI 进入规划态
- 允许 AI 在计划完成后通过专门工具提交计划
- 用户批准后再回执行态

你现在应该新增：

- `aicoder/tools/tools/enter_plan_mode.py`
- `aicoder/tools/tools/exit_plan_mode.py`
- 对应 handler
- 对应前端审批和展示块

### 3. 模式附件注入机制

优先级：高

建议直接抄 Claude Code 的核心思想：

- 当前模式不是只体现在一个布尔值里
- 模式变化时，要向模型动态注入“你现在处于什么状态、可以做什么、不可以做什么”

你现在应该做：

- 独立的 mode attachment 构造函数
- 在消息构建阶段注入
- 在上下文压缩后重新注入

可新增的后端模块建议：

- `aicoder/attachments.py`
- `aicoder/mode_messages.py`

### 4. 工具可见性随模式变化

优先级：高

建议直接对标 Claude Code：

- plan 模式下写工具不应该继续完整暴露给模型
- 不只是“调用时报错”
- 而是“工具列表本身就变了”

当前已经做了第一步，但建议继续加强：

- 不同模式生成不同的 tool registry 视图
- 前端也能知道当前有哪些工具可用

### 5. 结构化审批请求

优先级：高

建议直接抄它的产品思路：

- 审批不是一个简单 yes/no 弹窗
- 审批要带：
  - 工具名
  - 原因
  - 风险
  - 影响范围
  - diff 或命令摘要
  - 模式来源

你当前应该升级：

- `approval/request` 事件结构
- `ApprovalDialog` 展示结构

### 6. 工具结果摘要与计划模式压缩展示

优先级：中高

Claude Code 的体验一个关键点是：

- 工具真实输出很多
- 但 UI 和模型上下文看到的是被压缩和摘要后的结果

你现在已经在 `plan` 里做了一点摘要，建议继续抄：

- 不同工具不同摘要策略
- 用户 UI 看摘要
- 必要时可展开看原文

### 7. 模式切换状态机与循环

优先级：中高

建议直接抄它的思路：

- 模式切换不是 if/else 散落各处
- 应有独立状态流
- 可支持快捷键循环
- 可支持从 plan 恢复到之前模式

建议新增：

- `aicoder/permission_state.py`
- `aicoder/get_next_mode.py`

---

## 四、暂时不建议现在就重写的部分

这些部分容易让人产生“是不是换技术栈更先进”的冲动，但我建议先别碰。

### 1. 不建议现在把 Python 后端整体改成 Node/Rust/Go

原因：

- 当前瓶颈不是语言本身
- 当前瓶颈是 runtime 设计层级
- 如果现在迁语言，你会把大量时间花在搬运，而不是升级产品能力

更合理做法：

- 先把模式系统、工具流、审批流做先进
- 再评估 Python 是否真的成为性能或维护瓶颈

### 2. 不建议现在推翻 TUI 改成 Web UI

原因：

- Claude Code 的强项不在“是不是网页”
- 强项在 runtime 和 workflow
- 你现在的 TUI 仍然足够承载第一阶段改造

### 3. 不建议现在先做复杂多代理系统

原因：

- 当前单代理的 plan/act/runtime 还没打磨好
- 过早做 swarm、sub-agent 会把复杂度抬得很高

---

## 五、推荐改造顺序

建议分三阶段推进。

### 第一阶段：先把模式系统做像 Claude Code

目标：

- 从“两个模式”升级成“真正的权限状态机”

任务：

1. 完整实现 `default / acceptEdits / plan / bypassPermissions`
2. 统一权限决策入口
3. 工具可见性按模式变化
4. 前端显式展示当前模式

### 第二阶段：把计划流做像 Claude Code

目标：

- 不再只是 `/plan` `/act`

任务：

1. 新增 `EnterPlanMode` 工具
2. 新增 `ExitPlanMode` 工具
3. 新增计划提交和批准 UI
4. 动态注入 plan-mode 附件
5. 压缩后恢复模式提示

### 第三阶段：把审批与工作台 UI 做像 Claude Code

目标：

- 从“聊天工具”升级成“工作流工具”

任务：

1. 结构化审批请求
2. 工具执行过程卡片升级
3. 计划展示块升级
4. 状态栏、输入区、模式切换交互升级

---

## 六、最终结论

### 值得保留

- 后端主程序与会话骨架
- 工具抽象层
- 基础工具实现
- RPC 通信层
- TUI store 基础
- 测试体系

### 建议重写

- `aicoder/tools/executor.py`
- `aicoder/approval.py`
- `aicoder/commands.py` 中模式相关逻辑
- `aicoder/tools/system_prompt.py`
- TUI 的消息与审批呈现层

### 建议直接照 Claude Code 抄

- 权限模式状态机
- EnterPlanMode / ExitPlanMode 工具
- 模式附件注入机制
- 工具可见性动态变化
- 结构化审批流
- 工具结果摘要策略
- 模式切换与恢复状态机

---

## 七、一句话建议

当前项目最优策略不是“全量重写”，而是：

**保留现有骨架，优先重做权限模式系统、计划流和审批流，尽可能按 Claude Code 的运行时思路去抄。**

如果继续推进，下一份最值得写的文档是：

- `ClaudeCode化第一阶段实施方案.md`

内容应包含：

- 目标文件清单
- 新增模块清单
- 状态机设计
- RPC 事件变更
- 前端 UI 变更点
- 测试计划
