"""
核心编排器 - AiCoder 的入口函数
参考 Aider 的 main.py，简化为 v0.1 版本
负责：参数解析 → 模型创建 → IO 创建 → Coder 创建 → 启动主循环
"""
import os

# 在任何可能触发 litellm 导入的操作之前，禁止远程拉取模型价格表
# 避免国内网络访问 GitHub 超时导致启动卡住
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import argparse
import json
import sys

from . import __version__
from .coders.base_coder import Coder
from .io import InputOutput
from .models import Model, DEFAULT_MODEL_NAME


def load_config(config_path=None):
    """加载 AiCoder 配置文件（类似 Claude Code 的 settings.json）

    查找顺序：
    1. 命令行参数 --config
    2. AICODER_CONFIG 环境变量
    3. 默认 ~/.aicoder/settings.json

    配置文件格式：
    {
        "env": {
            "DEEPSEEK_API_KEY": "sk-...",
            "OPENAI_API_KEY": "sk-...",
            ...
        }
    }
    """
    if not config_path:
        config_path = os.environ.get("AICODER_CONFIG")
    if not config_path:
        config_path = os.path.join(os.path.expanduser("~"), ".aicoder", "settings.json")

    if not os.path.isfile(config_path):
        return

    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as err:
        print(f"Warning: Failed to load config {config_path}: {err}", file=sys.stderr)
        return

    env_vars = config.get("env", {})
    for key, value in env_vars.items():
        os.environ.setdefault(key, str(value))


def get_parser():
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="AiCoder - AI 结对编程命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "files",
        nargs="*",
        help="要添加到聊天的文件",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL_NAME,
        help=f"LLM 模型名称 (默认: {DEFAULT_MODEL_NAME})",
    )
    parser.add_argument(
        "--edit-format",
        "-e",
        default="whole",
        choices=["whole", "diff", "ask", "architect"],
        help="编辑格式 (默认: whole)",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="禁用 Git 自动提交",
    )
    parser.add_argument(
        "--no-auto-commits",
        action="store_true",
        help="禁用自动提交（但仍使用 Git 仓库信息）",
    )
    parser.add_argument(
        "--map-tokens",
        type=int,
        default=1024,
        help="仓库地图的 token 预算 (默认: 1024，设为 0 禁用)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="禁用流式输出",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="详细输出模式",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="自动确认所有提示",
    )
    parser.add_argument(
        "--message",
        "-msg",
        help="直接发送一条消息（非交互模式）",
    )
    parser.add_argument(
        "--config",
        help="配置文件路径 (默认: ~/.aicoder/settings.json)",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="启动文本用户界面 (TUI) 模式",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AiCoder v{__version__}",
    )

    return parser


def _check_api_key(model_name):
    """根据模型名称检查对应的 API Key 环境变量"""
    model_lower = model_name.lower()

    # 模型到环境变量的映射
    provider_env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "machao": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "google": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "cohere": "COHERE_API_KEY",
        "together": "TOGETHER_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "perplexity": "PERPLEXITY_API_KEY",
    }

    for key, env_var in provider_env_map.items():
        if key in model_lower:
            api_key = os.environ.get(env_var)
            if api_key:
                return api_key

    return os.environ.get("OPENAI_API_KEY")


def main(argv=None):
    """主入口函数 — 默认 TUI 模式"""
    if argv is None:
        argv = sys.argv[1:]

    parser = get_parser()
    args = parser.parse_args(argv)
    # 强制 TUI 模式
    args.tui = True

    # 1. 加载配置文件（类似 Claude Code 的 ~/.claude/settings.json）
    load_config(args.config)

    # 2. 创建 IO 实例
    io = InputOutput(
        pretty=True,
        yes=args.yes,
    )

    # 3. 检查 API Key
    api_key = _check_api_key(args.model)
    if not api_key:
        io.tool_error(f"未设置 API Key！请设置环境变量后再运行。")
        io.tool_output("")
        io.tool_output("  推荐方案：创建配置文件（类似 Claude Code 的 settings.json）：")
        io.tool_output("  Create ~/.aicoder/settings.json:")
        io.tool_output('  { "env": { "DEEPSEEK_API_KEY": "sk-your-key" } }')
        io.tool_output("")
        io.tool_output("  或在终端设置环境变量：")
        io.tool_output("  PowerShell:   $env:DEEPSEEK_API_KEY='sk-your-key-here'")
        io.tool_output("  Linux/Mac:    export DEEPSEEK_API_KEY=sk-your-key-here")
        io.tool_output("")
        io.tool_output("  如果使用其他模型，请参考 litellm 文档设置对应的环境变量。")
        return 1

    # 3. 创建模型实例
    try:
        main_model = Model(model_name=args.model)
    except Exception as err:
        io.tool_error(f"Failed to create model: {err}")
        return 1

    # 3. 收集要编辑的文件
    fnames = []
    if args.files:
        for fname in args.files:
            fpath = os.path.abspath(fname)
            if os.path.exists(fpath) and os.path.isfile(fpath):
                fnames.append(fpath)
            elif not os.path.exists(fpath):
                # 用户指定的文件不存在，询问是否创建
                if io.confirm_ask(f"File {fname} does not exist. Create it?"):
                    fnames.append(fpath)
                else:
                    io.tool_warning(f"Skipping {fname}")
            else:
                io.tool_warning(f"Skipping {fname}: not a file")

    # 4. 创建 Coder 实例
    try:
        coder = Coder.create(
            main_model=main_model,
            edit_format=args.edit_format,
            io=io,
            fnames=fnames,
            verbose=args.verbose,
            stream=not args.no_stream,
            auto_commits=not args.no_auto_commits,
            map_tokens=args.map_tokens,
        )
    except Exception as err:
        io.tool_error(f"Failed to create coder: {err}")
        return 1

    # 5. 初始化 Git 仓库（如果可用）
    repo = None
    if not args.no_git:
        try:
            from .repo import GitRepo
            repo = GitRepo(io, fnames=fnames if fnames else None)
            coder.repo = repo
            coder.root = repo.root
            io.tool_output(f"Git repository: {repo.root}")
        except (FileNotFoundError, ImportError) as err:
            if fnames:
                io.tool_warning(f"No git repository found. Git features disabled.")

    # 6. TUI 模式：启动交互式终端界面
    if args.tui:
        from .tui_app import AiCoderTUI
        app = AiCoderTUI(coder=coder, git_repo=repo)
        app.run(mouse=False)
        return 0

    # 7. 启动主循环（CLI 模式）
    from .commands import SwitchCoder

    try:
        if args.message:
            coder.run(with_message=args.message)
        else:
            # 交互模式：循环，处理 SwitchCoder
            while True:
                result = coder.run()
                if isinstance(result, SwitchCoder):
                    kwargs = result.kwargs
                    kwargs["io"] = io
                    kwargs.setdefault("fnames", list(coder.abs_fnames))
                    coder = Coder.create(**kwargs)
                    # 重新关联 Git
                    if not args.no_git:
                        try:
                            from .repo import GitRepo
                            repo = GitRepo(io, fnames=list(coder.abs_fnames) if coder.abs_fnames else None)
                            coder.repo = repo
                            coder.root = repo.root
                        except (FileNotFoundError, ImportError):
                            pass
                    continue
                break
    except KeyboardInterrupt:
        io.tool_warning("\nGoodbye!")
    except EOFError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
