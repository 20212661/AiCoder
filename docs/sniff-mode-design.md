# SNIFF / PLAN / ACT 三态模式设计

本文档定义 AiCoder 的三种运行模式及其职责边界。

---

## 1. 模式体系

AiCoder 有三种运行模式：

| 模式 | 定位 | 权限 |
|------|------|------|
| `sniff` | 只读侦察 | 仅读工具 + 只读 shell |
| `plan` | 规划方案 | 仅读工具 + 只读 shell |
| `act` | 执行修改 | 全部工具 |

切换命令：`/sniff`、`/plan`、`/act`。

---

## 2. 模式职责

### 2.1 SNIFF — 侦察模式

回答的问题：

- 这个代码库现在到底是什么情况？
- 关键入口在哪里？
- 哪些地方最可疑？
- 风险从哪里扩散？

特点：

- 以调查为主，以证据为主
- 允许结论不完整
- 不要求立即形成完整改造方案
- 输出偏调查报告

### 2.2 PLAN — 规划模式

回答的问题：

- 接下来应该怎么改？
- 改动顺序是什么？
- 影响哪些文件？
- 验收方式是什么？

特点：

- 以组织方案为主，以结构化步骤为主
- 输出应更收敛、更完整
- 输出偏方案文档

### 2.3 ACT — 执行模式

回答的问题：

- 现在我开始动手改什么？
- 改完了没有？
- 测试通过没有？

特点：

- 直接执行、修改文件、运行验证、汇报结果

---

## 3. SNIFF 与 PLAN 的关键差异

| 维度 | SNIFF | PLAN |
|------|-------|------|
| 目标 | 嗅探现状、找证据、找异常 | 组织行动步骤、明确实施顺序 |
| 输出 | 调查报告 | 方案文档 |
| 完整性 | 可以停在"不下结论但明确指出高风险区域" | 应该主动收束，给步骤和优先级 |
| 下一步 | 建议继续 sniff 或切 plan/act | 形成可执行计划，等待用户切 act |

---

## 4. SNIFF 的权限

### 允许

- `read_file`、`search_files`、`list_files`、`list_code_defs`
- `run_shell` 仅限只读命令：`pwd`、`ls`、`dir`、`cat`、`type`、`rg`、`find`、`git status`、`git diff`、`git log`

### 禁止

- `write_file`、`edit_file`
- 所有修改状态的 shell 命令：`rm`、`mv`、`cp`、`sed`、`git checkout`、`git reset`、包安装、构建发布

---

## 5. SNIFF 的输出模板

```text
Sniff Report

Current State:
- ...

Key Findings:
- ...

Root Cause Analysis:
- ...

Risk Assessment:
- ...

Conclusion:
- ...

Suggested Next Step:
- Continue /sniff
- Switch to /plan
- Switch to /act
```

---

## 6. 后端状态模型

```python
PermissionMode = Literal["sniff", "plan", "act"]
```

RPC `status/update` 和 `ready` 广播 `mode` 字段，值为 `"sniff"`、`"plan"` 或 `"act"`。

---

## 7. TUI 展示

状态栏显示当前模式：`SNIFF`、`PLAN`、`ACT`。

`/help` 说明：

- `/sniff` = inspect and investigate without editing
- `/plan` = turn findings into an implementation plan
- `/act` = execute changes

---

## 8. 安全要求

1. 绝不写文件
2. 绝不执行副作用 shell
3. 绝不绕过审批
4. 绝不降低危险命令防护
