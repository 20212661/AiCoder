# AiCoder

AI 结对编程命令行工具。支持自然语言对话来浏览、理解和修改代码库。

## 架构概览

```
aiCoder/
├── aicoder/              # Python 后端
│   ├── main.py           # CLI 入口
│   ├── agent_runtime.py  # AgentRuntime — 用户对话的唯一执行入口
│   ├── mode_definitions.py # 模式语义单一事实源（sniff/plan/act）
│   ├── coders/           # Coder 状态容器 + 提示词模板（不再分流子类）
│   ├── graph/            # LangGraph 节点和状态定义
│   ├── tools/            # 工具注册、执行、权限
│   ├── commands.py       # 斜杠命令系统
│   ├── rpc_io.py         # JSON-RPC 服务（--serve 模式）
│   ├── approval.py       # 审批控制器
│   ├── permission_modes.py  # 从 mode_definitions 派生的权限决策
│   └── tests/            # 后端测试
├── aicoder-tui/          # TypeScript TUI 前端（official-ink 运行时）
│   ├── src/
│   │   ├── index.tsx     # TUI 入口（直接启动 official-ink）
│   │   ├── official-ink/ # 唯一正式 UI 运行时
│   │   ├── hooks/        # 统一 backend hook
│   │   ├── stores/       # Zustand 状态管理
│   │   └── rpc/          # JSON-RPC 客户端和协议定义
│   └── package.json
├── docs/                 # 项目级文档
└── pyproject.toml        # Python 包配置
```

后端唯一主链：`Coder.run()` → `AgentRuntime.run_user_turn()` → LangGraph 图执行。支持 `sniff`（嗅探）、`plan`（规划）、`act`（执行）三种模式，语义由 `mode_definitions.py` 统一定义。TUI 唯一正式运行时为 `official-ink`，通过 JSON-RPC 2.0 over stdio 与后端通信。

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+（仅 TUI 开发需要）

### 安装后端

```bash
# 克隆仓库
git clone https://github.com/20212661/AiCoder.git
cd AiCoder

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate     # Windows
source venv/bin/activate  # macOS/Linux

# 安装（开发模式）
pip install -e ".[dev]"
```

### 配置 API Key

```bash
# 方式 1：生成配置文件模板
aicoder config init
# 然后编辑 ~/.aicoder/settings.json 添加 API Key

# 方式 2：环境变量
# PowerShell
$env:DEEPSEEK_API_KEY='sk-your-key-here'
# Linux/Mac
export DEEPSEEK_API_KEY=sk-your-key-here
```

### 启动 CLI

```bash
# 交互模式（默认）
aicoder

# 指定模型
aicoder -m openai/gpt-4

# 非交互模式（单条消息）
aicoder --message "explain this codebase"

# 恢复历史会话
aicoder --list-sessions
aicoder --resume <session-id>

# 也可以用 python -m 方式运行
python -m aicoder
```

### 启动 TUI

```bash
cd aicoder-tui

# 安装依赖
npm install

# 开发模式
npm run dev

# 构建
npm run build

# 运行构建产物
npm run start
```

TUI 会自动 spawn `python -m aicoder --serve` 作为后端子进程，通过 JSON-RPC 通信。

后端唯一主链是 `AgentRuntime + LangGraph`。`Coder` 仅作为状态容器（会话、工具注册、repo）。TUI 唯一正式运行时是 `official-ink`（基于 Ink 框架）。

## 运行模式

### 三种执行模式

| 模式 | 命令 | 工具范围 | Shell 策略 |
|------|------|----------|-----------|
| **Sniff**（嗅探） | `/sniff` | 只读探索 | 仅检查命令 |
| **Plan**（规划） | `/plan` | 只读探索 | 仅检查命令 |
| **Act**（执行） | `/act` | 全部工具 | 安全命令自动放行 |

- **Sniff 模式**（只读调查）：读取文件、搜索、查看目录，输出"嗅探报告"格式。不编辑文件。
- **Plan 模式**（只读规划）：读取文件、搜索、查看目录，输出结构化方案。不编辑文件。
- **Act 模式**（实现修改）：可以编辑、写入、运行命令。安全命令自动放行，其余需审批确认。

### `edit_format` 的现状

`--edit-format` CLI 参数（`whole`/`diff`/`ask`/`architect`）仅影响系统提示词风格，**不再决定运行时路径**。所有格式统一走 `AgentRuntime + LangGraph`。

## 权限与审批

所有文件编辑和危险操作需要用户审批确认：

- 安全命令（`ls`, `git status`, `cat` 等）自动放行
- 文件编辑（`edit_file`, `write_file`）需要审批
- 危险命令（`rm -rf /`, `mkfs` 等）绝对禁止
- `--yolo` 或 `--auto-approve` 可跳过所有审批（危险命令仍禁止）

详见 [permission-matrix.md](aicoder/docs/permission-matrix.md)。

## 测试

```bash
# 后端测试
pytest

# 后端测试（带覆盖率）
pytest --cov=aicoder

# TUI 类型检查
cd aicoder-tui && npm run typecheck

# TUI 构建
cd aicoder-tui && npm run build
```

## 已知限制

- RPC 模式（`--serve`）的兼容性需要更多实际联调验证
- TUI 当前为基础可运行状态，交互体验仍在迭代中
- 仅支持 litellm 兼容的模型 provider
- `src/components/` 和 `src/ink/root.tsx` 为 legacy 残留文件，可在后续清理中移除

## 文档

- [RPC 协议](docs/rpc-protocol.md) — 前后端 JSON-RPC 2.0 通信协议
- [权限矩阵](aicoder/docs/permission-matrix.md) — 工具权限和审批规则
- [运行时统一设计](aicoder/docs/runtime-unification.md) — LangGraph 主链架构
- [Typecheck 分类](aicoder-tui/docs/typecheck-triage.md) — TUI 类型错误修复记录

## 许可证

Apache-2.0
