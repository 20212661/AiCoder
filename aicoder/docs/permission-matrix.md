# 权限矩阵

## 概述

权限判断由两个模块协作完成：
- `permission_modes.py` — 模式级（plan/act）的工具权限决策
- `approval.py` — 细粒度命令安全和自动审批设置

决策链：`can_use_tool_in_mode()` → `ToolExecutor._get_permission_decision()` → `ApprovalController.should_auto_approve()`

## Plan 模式（只读探索）

| 工具 | 行为 | 说明 |
|------|------|------|
| `read_file` | allow | 读取文件 |
| `search_files` | allow | 正则搜索 |
| `list_files` | allow | 目录列表 |
| `list_code_defs` | allow | 代码定义 |
| `run_shell` | allow/deny | 仅允许安全检查命令（git status, ls, cat 等） |
| `edit_file` | **deny** | 禁止编辑 |
| `write_file` | **deny** | 禁止写入 |

## Act 模式（实现模式）

| 工具 | 默认行为 | 说明 |
|------|----------|------|
| `read_file` | ask | 需审批（可通过 `read_files=True` 自动放行） |
| `edit_file` | ask | 需审批（可通过 `edit_files=True` 自动放行） |
| `write_file` | ask | 需审批（可通过 `edit_files=True` 自动放行） |
| `run_shell` | allow/ask | 安全命令自动放行，其他需审批 |
| `list_files` | allow | 默认放行 |
| `search_files` | allow | 默认放行 |
| `list_code_defs` | allow | 默认放行 |

## Act 模式自动放行命令（`ACT_MODE_AUTO_APPROVED_COMMANDS`）

以下命令 base command 自动放行，无需审批：

- `mkdir` — 创建目录
- `touch` — 创建空文件

**以下命令已移除自动放行（需审批）：**

- ~~`rm`~~ — 删除文件
- ~~`rmdir`~~ — 删除空目录
- ~~`mv`~~ — 移动/重命名
- ~~`cp`~~ — 复制
- ~~`sed`~~ — 流编辑器

## 安全命令模式（`approval.py: SAFE_COMMAND_PATTERNS`）

当 `execute_safe_cmds=True`（默认开启）时，以下命令自动放行：

| 类别 | 命令 |
|------|------|
| 导航/查看 | ls, dir, cat, type, pwd, cd, echo, printf, head, tail, find, grep, rg, wc, sort, uniq, file, stat |
| Git 只读 | git status/log/diff/branch/show/rev-parse/remote -v/stash list/tag/describe/ls-files |
| 包管理查看 | npm/pnpm/yarn list/info/why/outdated, pip/pip3 list/show/freeze, cargo check/tree, go env/version/list |
| 版本查看 | node/python/ruby/rustc/gcc/clang --version, git/docker/kubectl version |
| 环境信息 | env, printenv, set, export, which, where, whereis, type |

## 绝对禁止命令（不可覆盖，`run_shell_handler.py: BLOCKED_PATTERNS`）

| 模式 | 说明 |
|------|------|
| `rm -rf /` | 删除根目录 |
| `rm -rf ~` | 删除用户主目录 |
| `rm -rf *` | 递归强制删除 |
| `dd if=... of=/dev/sd` | 原始磁盘写入 |
| `> /dev/sd` | 原始磁盘写入 |
| `chmod -R 777 /` | 根目录权限全开 |
| fork bomb | `:(){ :\|:& };:` |
| `mkfs` | 格式化文件系统 |
| `fdisk/parted` | 磁盘分区 |
| `> /dev/mem` | 内存写入 |
| `sysctl -w` | 内核参数修改 |

## 危险但可覆盖命令（需额外确认）

| 模式 | 说明 |
|------|------|
| `git push --force ... main/master` | 强制推送主分支 |
| `git reset --hard` | 丢弃所有未提交更改 |
| `git clean -f` | 删除未跟踪文件 |
| `rm -f` | 强制删除 |
| `chmod -R 777` | 递归权限全开 |
| `kill -9 1` | 杀死 init 进程 |
| `taskkill/pkill/killall -9` | 强制杀进程 |
| `shutdown` / `reboot` | 关机/重启 |

## YOLO 模式

当 `yolo=True` 或 `auto_approve_all=True` 时，所有工具调用自动放行，但 `run_shell_handler.py` 中的绝对禁止模式仍然生效（不可覆盖）。
