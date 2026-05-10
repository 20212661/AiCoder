import os, sys, time, shutil
from pathlib import Path
from typing import Any
from ..io import InputOutput
from ..models import Model, DEFAULT_MODEL_NAME
from .base_prompts import CoderPrompts
from ..commands import Commands, SwitchCoder
from ..permission_modes import get_visible_tool_specs

all_fences = [("```", "```"), ("````", "````"), ("<source>", "</source>"), ("<code>", "</code>")]


class Coder:
    edit_format = None
    gpt_prompts = CoderPrompts()
    fences = all_fences
    fence = fences[0]

    def __init__(self, main_model: Model, io: InputOutput | None = None, fnames: list[str] | None = None,
                 verbose: bool = False, stream: bool = True, auto_commits: bool = True,
                 map_tokens: int = 1024, session_id: str | None = None) -> None:
        if not fnames: fnames = []
        if io is None: io = InputOutput()
        self.io = io; self.main_model = main_model
        self.verbose = verbose; self.stream = stream and main_model.streaming
        self.auto_commits = auto_commits; self.map_tokens = map_tokens
        self.abs_fnames = set(); self.abs_read_only_fnames = set()
        self.cur_messages = []; self.done_messages = []
        self.partial_response_content = ""; self.multi_response_content = ""
        self.abs_root_path_cache = {}
        self.repo = None; self.aider_commit_hashes = set(); self.total_cost = 0.0
        self.summarizer = None; self.commit_before_message = []
        self.commands = Commands(io, self); self.root = os.getcwd()
        self._first_message = True; self._file_tree = None; self._repo_map_inst = None
        self.session_id = session_id
        self._first_user_message = None
        self._session_token_in = 0
        self._session_token_out = 0
        self._approval = None  # Set by main.py after loading settings
        self._cached_system_messages = None
        self._cached_system_key = None  # (model_name, mode) tuple
        self._init_tool_system()
        for fname in fnames:
            fname = Path(fname)
            if not fname.exists():
                try: fname.parent.mkdir(parents=True, exist_ok=True); fname.touch()
                except OSError: continue
            if not fname.is_file(): continue
            self.abs_fnames.add(str(fname.resolve()))
        if self.abs_fnames: self.root = self._find_common_root(self.abs_fnames)

    def _init_tool_system(self):
        from ..tools.registry import ToolRegistry
        from ..tools.executor import ToolExecutor, ToolCoordinator
        from ..tools.system_prompt import SystemPrompt
        from ..tools.result import ExecutionState
        # 内置工具 spec
        from ..tools.tools.edit_file import EDIT_FILE_SPEC
        from ..tools.tools.write_file import WRITE_FILE_SPEC
        from ..tools.tools.run_shell import RUN_SHELL_SPEC
        from ..tools.tools.read_file import READ_FILE_SPEC
        from ..tools.tools.search_files import SEARCH_FILES_SPEC
        from ..tools.tools.list_files import LIST_FILES_SPEC
        from ..tools.tools.list_code_defs import LIST_CODE_DEFS_SPEC
        # 内置工具 handler
        from ..tools.handlers.edit_file_handler import EditFileHandler
        from ..tools.handlers.write_file_handler import WriteFileHandler
        from ..tools.handlers.run_shell_handler import RunShellHandler
        from ..tools.handlers.read_file_handler import ReadFileHandler
        from ..tools.handlers.search_files_handler import SearchFilesHandler
        from ..tools.handlers.list_files_handler import ListFilesHandler
        from ..tools.handlers.list_code_defs_handler import ListCodeDefsHandler

        # 1. 加载用户插件（自动发现 ~/.aicoder/plugins/）
        from ..plugins import plugin_registry
        from ..plugins.loader import PluginLoader
        loader = PluginLoader(plugin_registry)
        num_loaded = loader.load_all()
        if num_loaded > 0:
            self.io.tool_output(f"Loaded {num_loaded} user plugin(s)")

        # 2. 注册内置工具 spec
        self.tool_registry = ToolRegistry()
        builtin_specs = [EDIT_FILE_SPEC, WRITE_FILE_SPEC, RUN_SHELL_SPEC, READ_FILE_SPEC,
                         SEARCH_FILES_SPEC, LIST_FILES_SPEC, LIST_CODE_DEFS_SPEC]
        for spec in builtin_specs:
            self.tool_registry.register(spec)

        # 3. 注册插件工具 spec（追加到内置工具之后）
        for plugin_spec in plugin_registry.get_tool_specs():
            self.tool_registry.register(plugin_spec)

        # 4. 注册内置工具 handler
        self._system_prompt = SystemPrompt()
        self.tool_coordinator = ToolCoordinator()
        builtin_handlers = [EditFileHandler(), WriteFileHandler(), RunShellHandler(),
                            ReadFileHandler(), SearchFilesHandler(), ListFilesHandler(), ListCodeDefsHandler()]
        for h in builtin_handlers:
            self.tool_coordinator.register(h)

        # 5. 注册插件工具 handler
        for handler_cls in plugin_registry.get_tool_handlers():
            handler = handler_cls()
            self.tool_coordinator.register(handler)

        self.tool_exec_state = ExecutionState()
        self.tool_executor = ToolExecutor(self.tool_coordinator, self, self.tool_exec_state)
        self._update_tool_model_info()

    def _update_tool_model_info(self):
        import platform
        from ..models import MODEL_TOKEN_LIMITS
        model_names = [k for k in MODEL_TOKEN_LIMITS if not k.startswith("machao-")]
        model_names += ["machao-flash", "machao-pro"]
        model_name = self.main_model.name.lower() if self.main_model else ""
        if "machao-pro" in model_name:
            from .base_prompts import MACHO_IDENTITY_PRO
            ai_identity = MACHO_IDENTITY_PRO
        elif "machao" in model_name:
            from .base_prompts import MACHO_IDENTITY_FLASH
            ai_identity = MACHO_IDENTITY_FLASH
        else:
            ai_identity = getattr(self.gpt_prompts, "ai_identity", "")
        self._system_prompt.configure(
            tools=get_visible_tool_specs(
                self.tool_registry.get_all(),
                self.tool_exec_state.mode,
            ),
            cwd=self.root.replace("\\", "/"),
            os_name=platform.system(),
            model_list=model_names,
            current_model=self.main_model.name,
            mode=self.tool_exec_state.mode,
            ai_identity=ai_identity,
        )

    def _find_common_root(self, paths: set[str]) -> str:
        if not paths: return os.getcwd()
        return str(Path(os.path.commonpath([Path(p).parent for p in paths])))

    @classmethod
    def create(cls, main_model: Model | None = None, edit_format: str | None = None,
               io: InputOutput | None = None, **kwargs: Any) -> "Coder":
        if not main_model: main_model = Model(DEFAULT_MODEL_NAME)
        if edit_format is None: edit_format = main_model.edit_format or "whole"
        from .wholefile_coder import WholeFileCoder
        from .editblock_coder import EditBlockCoder
        from .ask_coder import AskCoder
        from .architect_coder import ArchitectCoder
        coder_classes = {
            "whole": WholeFileCoder,
            "diff": EditBlockCoder,
            "ask": AskCoder,
            "architect": ArchitectCoder,
        }
        coder_cls = coder_classes.get(edit_format, WholeFileCoder)
        return coder_cls(main_model, io, **kwargs)

    def abs_root_path(self, path: str) -> str:
        if path in self.abs_root_path_cache: return self.abs_root_path_cache[path]
        # 阻止绝对路径穿越工作区
        p = Path(path)
        if p.is_absolute():
            try: p.relative_to(self.root)
            except ValueError:
                raise ValueError(f"Path traversal blocked: {path} is outside workspace {self.root}")
        res = str(Path(self.root) / path); res = str(Path(res).resolve())
        self.abs_root_path_cache[path] = res; return res

    def get_rel_fname(self, fname: str) -> str:
        try: return os.path.relpath(fname, self.root)
        except ValueError: return fname

    def get_inchat_relative_files(self) -> list[str]:
        return sorted(self.get_rel_fname(f) for f in self.abs_fnames)

    def get_all_relative_files(self) -> list[str]: return self.get_inchat_relative_files()
    def get_addable_relative_files(self) -> list[str]: return []

    def get_abs_fnames_content(self):
        for fname in list(self.abs_fnames):
            content = self.io.read_text(fname)
            if content is None: self.abs_fnames.discard(fname)
            else: yield fname, content

    def get_files_content(self):
        prompt = ""
        for fname, content in self.get_abs_fnames_content():
            rfn = self.get_rel_fname(fname)
            prompt += "\n" + rfn + "\n" + self.fence[0] + "\n" + content + self.fence[1] + "\n"
        return prompt

    def _build_workspace_info(self):
        if not self.repo: return ""
        try:
            r = self.repo.repo
            lines = ["# Workspace", ""]
            try: lines.append("Remote: " + r.remotes.origin.url)
            except Exception: pass
            try: lines.append("Branch: " + r.active_branch.name)
            except Exception: pass
            try: lines.append("HEAD: " + r.head.commit.hexsha[:7])
            except Exception: pass
            lines.append("")
            return "\n".join(lines)
        except Exception: return ""

    @staticmethod
    def _detect_cli_tools():
        tools = [
            "gh", "git", "docker", "podman", "kubectl", "helm",
            "aws", "gcloud", "az", "terraform", "pulumi",
            "npm", "yarn", "pnpm", "pip", "pip3", "cargo", "go", "bundle",
            "gradle", "mvn", "dotnet", "brew", "apt", "yum",
            "make", "cmake", "python", "python3", "node", "npx",
            "psql", "mysql", "redis-cli", "sqlite3", "mongosh",
            "curl", "jq", "grep", "sed", "awk", "wget",
            "code", "ansible", "rg", "fd",
        ]
        found = [t for t in tools if shutil.which(t)]
        if not found: return ""
        lines = ["# Detected CLI Tools", ""]
        lines.append(", ".join(found) + ".")
        lines.append("This list is not exhaustive, and other tools may be available.")
        lines.append("")
        return "\n".join(lines)

    def _build_file_tree(self):
        root = self.root; limit = 200
        ignore_dirs = {"node_modules", "__pycache__", ".git", ".venv", "venv",
                       "dist", "build", ".next", ".turbo", "target"}
        result = []; visited = set()
        queue = [(root, "")]; idx = 0
        while idx < len(queue) and len(result) < limit:
            abs_dir, rel_base = queue[idx]; idx += 1
            try: entries = sorted(os.listdir(abs_dir))
            except Exception: continue
            for entry in entries:
                if len(result) >= limit: break
                if entry == ".git": continue
                abs_path = os.path.join(abs_dir, entry)
                rel_path = (rel_base + "/" + entry) if rel_base else entry
                if rel_path in visited: continue
                visited.add(rel_path)
                try:
                    if os.path.isdir(abs_path):
                        if entry in ignore_dirs: continue
                        result.append((rel_path, True))
                        queue.append((abs_path, rel_path))
                    elif os.path.isfile(abs_path):
                        result.append((rel_path, False))
                except Exception:
                    result.append((rel_path + " [LOCKED]", False))
        if not result: return ""
        result.sort(key=lambda x: (0 if x[1] else 1, x[0].lower()))
        cwd = root.replace("\\", "/")
        lines = ["# Project File Tree (" + cwd + ")", ""]
        for rel_path, is_dir in result:
            display = rel_path + "/" if is_dir else rel_path
            depth = rel_path.count("/") + 1 if "/" in rel_path else 1
            indent = "  " * depth
            lines.append(indent + display)
        if len(result) >= limit:
            lines.append("")
            lines.append("(File list truncated. Use list_files on specific subdirectories if you need to explore further.)")
        lines.append("")
        return "\n".join(lines)

    def format_messages(self) -> list[dict[str, Any]]:
        from .message_builder import format_messages
        return format_messages(self)

    def get_chat_files_messages(self) -> list[dict[str, Any]]:
        from .message_builder import build_chat_files_messages
        return build_chat_files_messages(self)

    def get_repo_map(self) -> str | None:
        if not self.repo: return None
        # TODO: repo_map 用 tree-sitter 解析全仓库，189 个文件首次解析太慢（>15s）。
        # 暂时跳过，后续优化：限制文件数 + 惰性缓存 + 后台预计算。
        return None

    def run(self, with_message: str | None = None) -> str | None:
        self.show_announcements()
        try:
            if with_message:
                from ..agent_runtime import _create_runtime
                runtime = _create_runtime(self)
                return runtime.run_user_turn(with_message)
            while True:
                try:
                    um = self.get_input()
                    if not um: continue
                    from ..agent_runtime import _create_runtime
                    runtime = _create_runtime(self)
                    runtime.run_user_turn(um)
                except KeyboardInterrupt: self.keyboard_interrupt()
                except SwitchCoder as s: return s
        except EOFError: return

    def get_input(self):
        inchat = self.get_inchat_relative_files()
        ui = self.io.get_input(self.root, inchat, [], self.commands.get_commands() if self.commands else [], set())
        if ui and self.commands and self.commands.is_command(ui):
            r = self.commands.run(ui)
            if isinstance(r, str): return r
            return None
        return ui

    def _save_session(self):
        """Persist the current conversation to disk (non-blocking best-effort)."""
        if not self.session_id:
            return
        try:
            from ..session import save_session, SessionMeta

            meta = SessionMeta(
                session_id=self.session_id,
                created_at=time.time(),
                updated_at=time.time(),
                first_message=self._first_user_message or "",
                model_name=self.main_model.name if self.main_model else "unknown",
                edit_format=self.edit_format or "whole",
                token_in=self._session_token_in,
                token_out=self._session_token_out,
                root=self.root,
            )
            save_session(self.session_id, self.done_messages, self.cur_messages, meta)
        except Exception:
            pass

    def auto_commit(self):
        if not self.repo: return
        r = self.repo.commit(fnames=None, aider_edits=True, coder=self)
        if r: self.aider_commit_hashes.add(r[0])

    def process_response(self): pass

    def show_announcements(self):
        from .. import __version__
        self.io.tool_output("AiCoder v" + __version__)
        ml = "PLAN" if self.tool_exec_state.is_plan_mode else "ACT"
        self.io.tool_output("Model: " + self.main_model.name + " [" + str(self.edit_format) + "]  Mode: " + ml)

    def keyboard_interrupt(self):
        now = time.time()
        if hasattr(self, "_last_kb_interrupt") and self._last_kb_interrupt:
            if now - self._last_kb_interrupt < 2: self.io.tool_warning("Exiting..."); sys.exit()
        self.io.tool_warning("^C again to exit")
        self._last_kb_interrupt = now
