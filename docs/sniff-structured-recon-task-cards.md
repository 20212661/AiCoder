# SNIFF 结构化侦察增强任务卡

本文档用于把 `docs/sniff-structured-recon-prd.md` 拆成可直接交给 AI 执行的小任务。

---

## 任务卡 1：新增 `sniff` 独立辅助模块

### 目标

新增只服务于 `sniff` 模式的独立辅助模块，用于生成程序化侦察摘要。

### 读取文件

- `aicoder/coders/message_builder.py`
- `aicoder/coders/base_coder.py`
- `aicoder/tests/test_message_builder.py`

### 修改建议

新增：

- `aicoder/sniffing/__init__.py`
- `aicoder/sniffing/recon_summary.py`

在该模块中实现最小入口：

- `build_sniff_recon_summary(coder) -> str`

### 要求

- 只做只读摘要生成
- 不运行副作用命令
- 不依赖 persona
- 模块结构清晰，便于后续扩展

### 验收

- 新模块存在
- 有清晰入口函数
- 当前项目仍可正常导入

---

## 任务卡 2：生成“发酵区概况”和“嗅探入口”摘要

### 目标

让 `sniff` 能程序化生成仓库结构与入口候选摘要。

### 读取文件

- `aicoder/sniffing/recon_summary.py`
- `aicoder/coders/message_builder.py`
- `aicoder/tests/test_message_builder.py`

### 修改建议

第一版优先实现：

- 发酵区概况：
  - 根目录关键结构
  - 测试目录
  - 配置文件候选
- 嗅探入口：
  - 主入口文件候选
  - 命令入口候选
  - 工作流/状态入口候选

### 要求

- 允许启发式规则
- 允许信息不完整
- 不要求第一版非常聪明，但必须稳定

### 验收

- summary 中出现“发酵区概况”
- summary 中出现“嗅探入口”
- `pytest aicoder/tests/test_message_builder.py` 通过

---

## 任务卡 3：生成“构石痕迹”和“扩散范围候选”

### 目标

让 `sniff` 对仓库中的疑点和影响面有程序化候选判断。

### 读取文件

- `aicoder/sniffing/recon_summary.py`
- `aicoder/tests/test_message_builder.py`

### 修改建议

第一版可采用轻量规则，例如：

- 构石痕迹候选：
  - 重复入口文件命名
  - 文档和实现双路径
  - 明显 legacy / old / backup / copy 类信号
  - 命令层和状态层重复分叉信号
- 扩散范围候选：
  - 命令层
  - 状态层
  - RPC 层
  - TUI 层
  - 测试层

### 要求

- 明确这是“候选信号”，不是最终诊断
- 不要过度夸大
- 优雅降级

### 验收

- summary 中出现“构石痕迹”
- summary 中出现“扩散范围”或“污染扩散路径候选”
- 测试通过

---

## 任务卡 4：把程序化侦察摘要接入 `sniff` message attachment

### 目标

将程序化侦察摘要注入 `sniff` 的运行时消息构建链。

### 读取文件

- `aicoder/coders/message_builder.py`
- `aicoder/sniffing/recon_summary.py`
- `aicoder/tests/test_message_builder.py`

### 修改建议

在 `build_mode_messages(coder)` 的 `sniff` 分支：

1. 生成 `build_sniff_recon_summary(coder)`
2. 将 summary 拼入 `SNIFF` 附加消息
3. 保持中文“嗅探报告”字段一致

### 要求

- `plan` / `act` 不得接入该摘要
- 若 summary 为空，也不能报错
- 风格与现有 sniff 精神模式一致

### 验收

- `sniff` attachment 包含程序化摘要
- `plan` / `act` attachment 不包含
- `pytest aicoder/tests/test_message_builder.py` 通过

---

## 任务卡 5：强化 `sniff` 提示词与摘要协同

### 目标

让提示词与程序化摘要形成双层约束，而不是互相脱节。

### 读取文件

- `aicoder/tools/system_prompt.py`
- `aicoder/tests/test_system_prompt.py`
- `aicoder/tests/test_message_builder.py`

### 修改建议

1. 在 `sniff` prompt 中明确说明：
   - 优先吸收附加的侦察摘要
   - 围绕固定中文结构完成“嗅探报告”
2. 明确 summary 是调查支架，不是最终结论

### 要求

- 不污染 `plan` / `act`
- 仍然强调证据驱动和严格只读

### 验收

- `pytest aicoder/tests/test_system_prompt.py` 通过
- `pytest aicoder/tests/test_message_builder.py` 通过

---

## 任务卡 6：补全测试并做全量验收

### 目标

确保结构化侦察增强没有破坏当前系统稳定性。

### 验收命令

```powershell
pytest
cd aicoder-tui
cmd /c npm run typecheck
cmd /c npm run build
```

### 重点检查

- `sniff` 有程序化摘要
- `sniff` 输出结构仍是中文“嗅探报告”
- `plan` / `act` 未被污染
- TUI 构建正常

---

## 可直接交给 AI 的总提示词

```text
请根据 docs/sniff-structured-recon-prd.md 和 docs/sniff-structured-recon-task-cards.md，实施 sniff 结构化侦察增强。

目标：
在保持 sniff 严格只读的前提下，加入程序化侦察摘要生成能力，减少 sniff 输出完全依赖模型临场发挥的程度。

约束：
1. 只增强 sniff，不污染 plan / act。
2. 允许新增独立 sniff 辅助模块。
3. 侦察摘要必须只使用只读信息。
4. 摘要是支架，不是最终回答替代品。
5. 保持当前中文“嗅探报告”体系。

执行要求：
1. 按任务卡顺序推进。
2. 每完成一个阶段就补测试。
3. 最后运行：
   - pytest
   - aicoder-tui 下 npm run typecheck
   - aicoder-tui 下 npm run build

输出：
1. 改了哪些文件
2. 程序化侦察摘要新增了什么
3. sniff 相比原来稳定了哪些地方
4. 测试结果
5. 后续还可增强的点
```

