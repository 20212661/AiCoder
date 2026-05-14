"""
核心编排器 - AiCoder 的入口函数
参考 Aider 的 main.py，简化为 v0.1 版本
负责：参数解析 → 配置加载 → 模型创建 → Coder 创建 → 启动主循环
"""
import os

# 在任何可能触发 litellm 导入的操作之前，禁止远程拉取模型价格表
# 避免国内网络访问 GitHub 超时导致启动卡住
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import argparse
import sys

from . import __version__
from .approval import ApprovalController, load_approval_settings
from .coders.base_coder import Coder
from .config import Settings, apply_env_vars, init_config, load_settings
from .exceptions import ConfigError
from .io import InputOutput
from .models import DEFAULT_MODEL_NAME, Model
from .session import list_sessions, load_session, new_session_id


def load_config(config_path=None):
    """加载配置文件并用 pydantic 校验，然后注入环境变量。

    优先级链：CLI参数 > 环境变量 > 配置文件 > 默认值
    """
    settings = load_settings(config_path)
    apply_env_vars(settings)
    return settings


def get_parser():
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="AiCoder - AI 结对编程命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=False)

    # config init 子命令
    config_parser = subparsers.add_parser("config", help="配置管理")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_init = config_sub.add_parser("init", help="生成配置文件模板")
    config_init.add_argument("--path", help="配置文件路径 (默认: ~/.aicoder/settings.json)")

    files_arg = parser.add_argument(
        "files",
        nargs="*",
        default=[],
        help="要添加到聊天的文件",
    )
    # argparse bug: subparser 存在时，nargs="*" 的位置参数会被设为 required=True
    files_arg.required = False
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
        help="编辑格式 — 仅影响系统提示词，不影响运行时路径 (默认: whole)",
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
        "--no-tui",
        action="store_true",
        help=argparse.SUPPRESS,  # deprecated, CLI is now default
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help="恢复之前的会话 (使用 --list-sessions 查看可用会话)",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="列出所有历史会话",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="不自动保存会话历史",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="YOLO 模式：自动批准所有操作（跳过所有确认）",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="自动批准所有操作（同 --yolo）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AiCoder v{__version__}",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="以 JSON-RPC 服务模式启动（供外部 TUI 调用）",
    )
    parser.add_argument(
        "--runtime",
        choices=["legacy", "langchain"],
        default="legacy",
        help="Agent runtime backend to use (default: legacy)",
    )

    return parser


def _check_api_key(model_name):
    """根据模型名称检查对应的 API Key 环境变量

    使用精确前缀匹配（provider/ 或 provider- 格式），避免子串误匹配。
    例如 "openai/gpt-4" 匹配 OPENAI_API_KEY，但 "machao-openai-style" 不会误匹配。
    """
    model_lower = model_name.lower()

    # 按 provider 前缀匹配（支持 "provider/" 和 "provider-" 两种格式）
    # 键为 provider 名称前缀，值为环境变量名
    provider_env_map = [
        ("deepseek/", "DEEPSEEK_API_KEY"),
        ("deepseek-", "DEEPSEEK_API_KEY"),
        ("machao/", "DEEPSEEK_API_KEY"),
        ("machao-", "DEEPSEEK_API_KEY"),
        ("openai/", "OPENAI_API_KEY"),
        ("openai-", "OPENAI_API_KEY"),
        ("anthropic/", "ANTHROPIC_API_KEY"),
        ("anthropic-", "ANTHROPIC_API_KEY"),
        ("claude-", "ANTHROPIC_API_KEY"),
        ("gemini/", "GEMINI_API_KEY"),
        ("gemini-", "GEMINI_API_KEY"),
        ("google/", "GEMINI_API_KEY"),
        ("google-", "GEMINI_API_KEY"),
        ("groq/", "GROQ_API_KEY"),
        ("groq-", "GROQ_API_KEY"),
        ("cohere/", "COHERE_API_KEY"),
        ("cohere-", "COHERE_API_KEY"),
        ("together/", "TOGETHER_API_KEY"),
        ("together-", "TOGETHER_API_KEY"),
        ("mistral/", "MISTRAL_API_KEY"),
        ("mistral-", "MISTRAL_API_KEY"),
        ("perplexity/", "PERPLEXITY_API_KEY"),
        ("perplexity-", "PERPLEXITY_API_KEY"),
    ]

    for prefix, env_var in provider_env_map:
        if model_lower.startswith(prefix):
            api_key = os.environ.get(env_var)
            if api_key:
                return api_key

    # 回退：检查 OPENAI_API_KEY（litellm 默认使用）
    return os.environ.get("OPENAI_API_KEY")


def main(argv=None):
    """主入口函数 — 默认 TUI 模式"""
    if argv is None:
        argv = sys.argv[1:]

    parser = get_parser()
    # argparse 的 subparser + nargs="*" 组合 bug：
    # 即使 files 是可选位置参数，subparser 存在时也会被当作必需。
    # 用 parse_known_args 绕过，保证 --serve 等零参数模式正常工作。
    args, _ = parser.parse_known_args(argv)
    if not hasattr(args, 'files') or args.files is None:
        args.files = []

    # 处理 config init 子命令
    if args.subcommand == "config" and args.config_action == "init":
        try:
            path = init_config(getattr(args, "path", None))
            print(f"Config template created: {path}")
            print("Edit it to add your API keys and preferences.")
        except ConfigError as err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
        return 0

    # 【会话查询】处理 --list-sessions 命令
    if args.list_sessions:
        sessions = list_sessions()
        if not sessions:
            print("No saved sessions.")
        else:
            print(f"{'SESSION ID':<14} {'MODEL':<18} {'MESSAGES':>8}  FIRST MESSAGE")
            print("-" * 80)
            for s in sessions:
                sid = s.get("session_id", "")[:12]
                model = s.get("model_name", "?")[:18]
                count = s.get("message_count", 0)
                first = (s.get("first_message", "") or "")[:40]
                print(f"{sid:<14} {model:<18} {count:>8}  {first}")
        return 0

    # 【配置】加载配置文件（pydantic 校验 + 环境变量注入）
    settings = Settings()
    try:
        settings = load_config(args.config)
    except ConfigError as err:
        print(f"Config error: {err}", file=sys.stderr)

    # 配置优先级：CLI参数 > 环境变量 > 配置文件 > 默认值
    if args.model == DEFAULT_MODEL_NAME and settings.default_model:
        args.model = settings.default_model
    if args.edit_format == "whole" and settings.default_edit_format:
        args.edit_format = settings.default_edit_format

    # 【IO】创建 IO 实例
    io = InputOutput(
        pretty=True,
        yes=args.yes,
    )

    # 【认证】检查 API Key
    api_key = _check_api_key(args.model)
    if not api_key:
        io.tool_error("未设置 API Key！请设置环境变量后再运行。")
        io.tool_output("")
        io.tool_output("  推荐方案：运行 aicoder config init 生成配置模板")
        io.tool_output("  然后编辑 ~/.aicoder/settings.json 添加 API Key")
        io.tool_output("")
        io.tool_output("  或在终端设置环境变量：")
        io.tool_output("  PowerShell:   $env:DEEPSEEK_API_KEY='sk-your-key-here'")
        io.tool_output("  Linux/Mac:    export DEEPSEEK_API_KEY=sk-your-key-here")
        io.tool_output("")
        io.tool_output("  如果使用其他模型，请参考 litellm 文档设置对应的环境变量。")
        return 1

    # 【模型】创建模型实例
    try:
        main_model = Model(model_name=args.model)
    except Exception as err:
        io.tool_error(f"Failed to create model: {err}")
        return 1

    # 【文件】收集要编辑的文件
    fnames = []
    if args.files:
        for fname in args.files:
            fpath = os.path.abspath(fname)
            if os.path.exists(fpath) and os.path.isfile(fpath):
                fnames.append(fpath)
            elif not os.path.exists(fpath):
                if io.confirm_ask(f"File {fname} does not exist. Create it?"):
                    fnames.append(fpath)
                else:
                    io.tool_warning(f"Skipping {fname}")
            else:
                io.tool_warning(f"Skipping {fname}: not a file")

    # 【Git】初始化 Git 仓库（在 Coder 创建之前，确保依赖就绪）
    repo = None
    if not args.no_git:
        try:
            from .repo import GitRepo
            repo = GitRepo(io, fnames=fnames if fnames else None)
            io.tool_output(f"Git repository: {repo.root}")
        except (FileNotFoundError, ImportError):
            if fnames:
                io.tool_warning("No git repository found. Git features disabled.")

    # 【会话】恢复或创建会话 ID（在 Coder 创建之前准备数据）
    session_id = None
    session_data = None
    if args.resume:
        session_data = load_session(args.resume)
        if not session_data:
            io.tool_error(f"Session not found: {args.resume}")
            return 1
    elif not args.no_save:
        session_id = new_session_id()

    # 【审批】加载自动批准设置
    approval_settings = load_approval_settings()
    if args.yolo or args.auto_approve:
        approval_settings.yolo = True
        io.tool_output("YOLO MODE — all operations auto-approved")

    # 【Coder】创建 Coder 实例
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

    # 关联 Git 仓库到 Coder
    if repo:
        coder.repo = repo
        coder.root = repo.root

    # 关联会话到 Coder
    if session_data:
        meta, done, cur = session_data
        coder.done_messages = done
        coder.cur_messages = cur
        coder.session_id = meta.session_id
        coder._first_user_message = meta.first_message
        io.tool_output(f"Resumed session: {meta.session_id} ({meta.message_count} messages)")
    elif session_id:
        coder.session_id = session_id

    # 关联审批控制器到 Coder
    coder._approval = ApprovalController(approval_settings)

    # 设置 runtime 后端
    coder.runtime = args.runtime

    # 【启动】RPC 服务模式、CLI 模式
    if args.serve:
        from .rpc_io import JsonRpcIO
        rpc_io = JsonRpcIO()
        coder.io = rpc_io
        coder._approval = ApprovalController(approval_settings)
        rpc_io.serve(coder)
        return 0

    # 【CLI】启动纯 CLI 主循环
    from .commands import SwitchCoder

    try:
        if args.message:
            coder.run(with_message=args.message)
        else:
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
                            repo = GitRepo(
                                io,
                                fnames=list(coder.abs_fnames) if coder.abs_fnames else None,
                            )
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
