# SNIFF Mode 实施计划

本文档记录 sniff mode 的实施状态。sniff 已作为独立 mode 完成，与 plan、act 并列。

---

## 1. 最终目标（已完成）

把模式体系从：

- `plan`
- `act`

升级为：

- `sniff`
- `plan`
- `act`

并满足：

1. `sniff` 是独立 mode，不依赖任何 persona
2. `sniff` 的语义是"侦察/嗅探/证据收集"，不是"规划"
3. `sniff` 是严格只读模式
4. 不能破坏统一 runtime、工具链和审批链

---

## 2. 已完成的修改

### 2.1 mode 语义升级

- `aicoder/graph/state.py` — `PermissionMode = Literal["sniff", "plan", "act"]`
- `aicoder/permission_modes.py` — sniff 共用 plan 的只读权限矩阵
- `aicoder/tools/result.py` — `is_plan_mode` 对 sniff 也返回 True
- `aicoder/agent_runtime.py` — 直接传递 mode 值
- `aicoder/coders/base_coder.py` — 透传实际 mode 给 system prompt

### 2.2 权限矩阵

sniff 模式与 plan 模式共享同一套只读权限：

- 允许：`read_file`、`search_files`、`list_files`、`list_code_defs`、只读 `run_shell`
- 禁止：`write_file`、`edit_file`、所有副作用 shell

### 2.3 system prompt

- `aicoder/tools/system_prompt.py` — 新增 SNIFF MODE 提示词分支，输出偏调查报告

### 2.4 命令系统

- `/sniff` → `mode = "sniff"`
- `/plan` → `mode = "plan"`
- `/act` → `mode = "act"`

### 2.5 RPC 状态广播

- `aicoder/rpc_io.py` — mode 字段直接传 `"sniff"` / `"plan"` / `"act"`

### 2.6 TUI 状态栏

- StatusBar 显示 `SNIFF` / `PLAN` / `ACT`
- SlashCommandMenu 和 InputBox 的 help 文案已更新

---

## 3. 测试覆盖

- `/sniff` 设置 `mode = "sniff"`
- sniff 模式隐藏编辑工具
- sniff 禁止写文件和副作用 shell
- sniff 允许读工具和只读 shell
- `status/update` 正确广播 `mode = "sniff"`
- sniff 模式初始状态正确

---

## 4. 验证命令

```bash
pytest
cd aicoder-tui && npx tsc --noEmit
```
