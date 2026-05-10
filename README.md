# AiCoder

AI 结对编程命令行工具。支持自然语言对话来浏览、理解和修改代码库。

## 架构概览

```
aiCoder/
├── aicoder/              # Python 后端
│   ├── main.py           # CLI 入口
│   ├── agent_runtime.py  # LangGraph 执行引擎（默认主链）
│   ├── coders/           # 编辑格式引擎（whole/diff/ask/architect）
│   ├── graph/            # LangGraph 节点和状态定义
│   ├── tools/            # 工具注册、执行、权限
│   ├── commands.py       # 斜杠命令系统
│   ├── rpc_io.py         # JSON-RPC 服务（--serve 模式）
│   ├── approval.py       # 审批控制器
│   ├── permission_modes.py  # plan/act 模式权限矩阵
│   └── tests/            # 后端测试（覆盖核心运行时、权限、工具、RPC 与图工作流）
├── aicoder-tui/          # TypeScript TUI 前端
│   ├── src/
│   │   ├── index.tsx     # TUI 入口
│   │   ├── rpc/          # JSON-RPC 客户端和协议定义
│   │   ├── components/   # UI 组件
│   │   ├── hooks/        # React hooks
│   │   └── stores/       # Zustand 状态管理
│   └── package.json
├── docs/                 # 项目级文档
│   ├── rpc-protocol.md
│   ├── permission-matrix.md
│   └── ...
└── pyproject.toml        # Python 包配置
```

后端通过 LangGraph 构建的节点流水线执行 AI 对话，支持 plan（只读探索）和 act（实现修改）两种模式。TUI 通过 JSON-RPC 2.0 over stdio 与后端通信。

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

## 运行模式

### `--serve` 模式

以 JSON-RPC 服务启动，供 TUI 或其他前端调用：

```bash
aicoder --serve
```

后端通过 stdin/stdout 收发 JSON-RPC 2.0 消息。stderr 仅保留异常或必要诊断输出，不参与协议通信。

### Plan / Act 模式

- **Plan 模式**（只读）：只能读取文件、搜索、查看目录，不能编辑或写入。适合探索代码库。
- **Act 模式**（实现）：可以编辑、写入、运行命令。需要审批确认（除安全命令外）。

在 CLI 中用 `/plan` 和 `/act` 切换模式。

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

- 旧的 Legacy 主循环已从默认执行路径中移除，当前统一通过 `AgentRuntime` 驱动 LangGraph 主链
- RPC 模式（`--serve`）的兼容性需要更多实际联调验证
- TUI 当前为基础可运行状态，交互体验仍在迭代中
- 仅支持 litellm 兼容的模型 provider

## 文档

- [RPC 协议](docs/rpc-protocol.md) — 前后端 JSON-RPC 2.0 通信协议
- [权限矩阵](aicoder/docs/permission-matrix.md) — 工具权限和审批规则
- [运行时统一设计](aicoder/docs/runtime-unification.md) — LangGraph 主链架构
- [Typecheck 分类](aicoder-tui/docs/typecheck-triage.md) — TUI 类型错误修复记录

## 许可证

Apache-2.0
