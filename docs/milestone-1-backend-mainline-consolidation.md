# 里程碑 1：后端主链收口

## 目标

将当前项目的后端执行路径收口为一条主链，避免长期并存的双实现带来维护成本、行为不一致和安全绕过问题。

本里程碑完成后，应达到以下状态：

- 后端只保留一条明确的主执行链
- 命令执行统一走工具系统
- 权限判断统一走同一入口
- 会话持久化、总结、工具循环不再重复维护
- 文档能明确说明当前唯一主链

## 背景问题

当前项目存在以下典型问题：

- legacy `Coder` 主循环和 LangGraph runtime 并存
- 工具调用、总结、持久化、auto commit 等职责重复实现
- `/run`、`/git` 等命令可能绕过统一工具执行链
- 权限逻辑分散，后续很容易出现“某条路径没加限制”的风险

## 本里程碑范围

要做：

- 梳理并确定唯一后端主链
- 收口命令执行入口
- 收紧并统一权限入口
- 删除或降级 legacy 路径的主职责
- 补充必要测试和文档

不做：

- 大规模新增功能
- 多 Agent 协作
- 高级索引系统重构
- 云端同步或复杂远程能力

## AI 执行总要求

请按以下原则执行：

1. 先阅读相关代码与测试，再动手修改。
2. 每次只解决一个收口问题，不要顺手扩展功能。
3. 任何 shell 执行必须统一接入工具系统。
4. 不要覆盖或回滚用户已有改动。
5. 修改后必须运行验证命令，并明确说明是否通过。
6. 如果发现收口会影响现有交互，需要先在结果里说明取舍。

---

## 任务 1：建立后端整改基线

### 目标

确认当前后端真实状态，并形成可追踪的整改基线。

### 需要阅读

- `README.md`
- `pyproject.toml`
- `aicoder/main.py`
- `aicoder/coders/base_coder.py`
- `aicoder/agent_runtime.py`
- `aicoder/graph/workflow.py`
- `aicoder/graph/nodes.py`

### 需要执行

1. 梳理当前后端入口与执行链路。
2. 运行：
   - `pytest`
3. 新建或更新基线文档，记录：
   - 当前后端主入口
   - 当前存在的双路径
   - 当前通过项
   - 当前风险项

### 验收标准

- 能清楚说明目前后端到底有几条执行链
- pytest 可用状态有明确记录

---

## 任务 2：输出后端主链统一设计

### 目标

明确“保留哪条主链，淘汰哪条路径”。

### 需要阅读

- `aicoder/coders/base_coder.py`
- `aicoder/agent_runtime.py`
- `aicoder/graph/workflow.py`
- `aicoder/graph/nodes.py`
- `aicoder/commands.py`

### 需要执行

1. 列出两条执行链中的重复职责：
   - 模型调用
   - 工具解析
   - 工具循环
   - 审批
   - 持久化
   - 总结
   - auto commit
2. 产出统一设计文档，建议放到：
   - `aicoder/docs/runtime-unification.md`
3. 文档中明确：
   - 推荐保留的唯一主链
   - legacy 路径中哪些逻辑需要迁移
   - 哪些逻辑需要废弃

### 验收标准

- 设计文档能直接指导后续代码改造
- 明确唯一主链，不保留模糊状态

---

## 任务 3：收口 `/run` 和 `/git`

### 目标

命令层不再直接执行 shell，统一走工具系统。

### 需要阅读

- `aicoder/commands.py`
- `aicoder/tools/executor.py`
- `aicoder/tools/result.py`
- `aicoder/tools/handlers/run_shell_handler.py`
- `aicoder/tests/test_commands.py`

### 需要执行

1. 找出直接 `subprocess.run` 的路径。
2. 将 `/run` 和 `/git` 改为构造 `ToolCall("run_shell", ...)`。
3. 统一交给 `coder.tool_executor.execute(...)`。
4. 保证仍保留原有命令交互形式。
5. 补测试覆盖：
   - `/run echo hello`
   - `/git status`
   - 危险命令审批

### 验收标准

- 命令系统不再直接执行 shell
- `/run` 和 `/git` 进入统一审批/超时/结果处理链

---

## 任务 4：统一权限入口并收紧默认策略

### 目标

把权限模型从“可跑”提升到“适合 AI Coding CLI 默认开启”。

### 需要阅读

- `aicoder/permission_modes.py`
- `aicoder/approval.py`
- `aicoder/tools/handlers/run_shell_handler.py`
- `aicoder/tests/test_permission_modes.py`
- `aicoder/tests/test_approval.py`
- `aicoder/tests/test_graph_permissions.py`

### 需要执行

1. 梳理当前自动批准的命令集合。
2. 收紧默认自动放行范围：
   - 保留只读/低风险命令
   - 去掉 `rm`、`rmdir`、`mv`、`cp`、`sed` 等默认自动放行
3. 对齐 `permission_modes.py` 与 `approval.py`。
4. 新建权限矩阵文档：
   - `aicoder/docs/permission-matrix.md`

### 验收标准

- plan 模式仍保持只读
- act 模式默认更保守
- 文档与代码一致

---

## 任务 5：移除或降级 legacy 主循环职责

### 目标

逐步让 legacy `Coder` 路径退出主执行职责，只保留必要兼容层。

### 需要阅读

- `aicoder/coders/base_coder.py`
- `aicoder/agent_runtime.py`
- `aicoder/graph/nodes.py`
- `aicoder/graph/workflow.py`
- 相关测试文件

### 需要执行

1. 基于统一设计文档，确认哪些方法已不应继续承担主职责。
2. 优先处理这些位置：
   - `Coder.run()`
   - `_send_message_inner()`
   - `_process_tool_calls()`
   - `_process_legacy_edits()`
3. 目标不是一次性删空所有旧代码，而是：
   - 主入口只走一条链
   - 旧逻辑若保留，也不再是默认主路径
4. 更新测试，确保新主链可工作。

### 验收标准

- 默认执行路径只有一条
- 不再依赖环境变量长期切换两套核心运行时

---

## 任务 6：补后端验证闭环

### 目标

确保主链收口后不是“看起来更整洁”，而是真能稳定跑。

### 需要执行

1. 跑完整后端测试：
   - `pytest`
2. 如有必要，新增最小冒烟验证：
   - CLI 单轮输入
   - `--serve` 模式启动
3. 更新总结文档，记录：
   - 完成项
   - 未完成项
   - 剩余风险

### 验收标准

- 后端收口后测试仍可通过
- 能用一句话说清“现在系统默认怎么跑”

---

## 建议执行顺序

1. 建立后端整改基线
2. 输出后端主链统一设计
3. 收口 `/run` 和 `/git`
4. 统一权限入口并收紧默认策略
5. 移除或降级 legacy 主循环职责
6. 补后端验证闭环

---

## 每次执行后的输出格式

请严格按以下格式汇报：

1. 分析
   - 阅读了哪些文件
   - 判断了什么问题
   - 准备怎么改
2. 实施
   - 修改了哪些文件
   - 为什么这么改
3. 验证
   - 跑了哪些命令
   - 是否通过
4. 总结
   - 当前完成到哪个任务
   - 还剩什么风险
   - 下一步建议做什么
