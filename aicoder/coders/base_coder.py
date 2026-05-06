import os, sys, time, shutil
from pathlib import Path
from typing import Any
from ..io import InputOutput
from ..models import Model, DEFAULT_MODEL_NAME
from ..exceptions import LLMError
from .base_prompts import CoderPrompts
from ..commands import Commands, SwitchCoder

all_fences = [("```", "```"), ("````", "````"), ("<source>", "</source>"), ("<code>", "</code>")]

# Named constants — avoid magic numbers
MAX_TOOL_CALL_ROUNDS = 5
LLM_MAX_RETRIES = 3
CONTEXT_RESERVE_TOKENS = 512
EMERGENCY_KEEP_MESSAGES = 16

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
        self.reflected_message = None; self.num_reflections = 0; self.max_reflections = 3
        self.shell_commands = []; self.abs_root_path_cache = {}
        self.repo = None; self.aider_commit_hashes = set(); self.total_cost = 0.0
        self.summarizer = None; self.commit_before_message = []
        self._context_mgr = None  # initialised lazily in _trim_context_for_model
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
            tools=self.tool_registry.get_all(),
            cwd=self.root.replace("\\", "/"),
            os_name=platform.system(),
            model_list=model_names,
            current_model=self.main_model.name,
            mode="plan" if self.tool_exec_state.is_plan_mode else "act",
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
        import sys as _sys
        from .message_builder import format_messages, build_system_messages, build_chat_files_messages
        _sys.stderr.write("[DBG]   build_system_messages\n"); _sys.stderr.flush()
        msgs = list(build_system_messages(self))
        msgs.extend(self.done_messages)
        _sys.stderr.write("[DBG]   get_repo_map\n"); _sys.stderr.flush()
        repo_map = self.get_repo_map()
        _sys.stderr.write(f"[DBG]   repo_map={bool(repo_map)}\n"); _sys.stderr.flush()
        if repo_map:
            msgs += [dict(role="user", content=repo_map), dict(role="assistant", content="Ok.")]
        _sys.stderr.write("[DBG]   build_chat_files\n"); _sys.stderr.flush()
        msgs.extend(build_chat_files_messages(self))
        msgs.extend(self.cur_messages)
        return msgs

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
            if with_message: self.run_one(with_message); return self.partial_response_content
            while True:
                try:
                    um = self.get_input()
                    if not um: continue
                    self.run_one(um)
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

    def run_one(self, user_message: str) -> None:
        self.init_before_message()
        message = user_message
        while message:
            self.reflected_message = None; self.shell_commands = []
            try: self.send_message(message)
            except SwitchCoder as s: raise s
            if not self.reflected_message: break
            if self.num_reflections >= self.max_reflections: return
            self.num_reflections += 1; message = self.reflected_message

    def init_before_message(self):
        self.partial_response_content = ""; self.multi_response_content = ""
        self.reflected_message = None; self.num_reflections = 0
        self.tool_exec_state.reset()

    def send_message(self, message: str) -> None:
        if self.repo: self.commit_before_message.append(self.repo.get_head_commit_sha())
        if self._first_user_message is None:
            self._first_user_message = message
        self._session_token_in += self.main_model.token_count(message) if self.main_model else 0
        self.cur_messages.append(dict(role="user", content=message))
        try:
            self._send_message_inner()
        except LLMError as err:
            self.io.tool_error(
                f"LLM API FAILURE: {err}\n"
                f"  Check: API key, network, model availability.\n"
                f"  Tip: try /model to switch models."
            )
            self.done_messages.extend(self.cur_messages); self.cur_messages = []

    def _send_message_inner(self) -> None:
        import sys as _sys
        for _ in range(MAX_TOOL_CALL_ROUNDS):
            _sys.stderr.write("[DBG] _trim_context\n"); _sys.stderr.flush()
            self._trim_context_for_model()
            _sys.stderr.write("[DBG] format_messages\n"); _sys.stderr.flush()
            messages = self.format_messages()
            # Exponential backoff: 3 retries with 1s / 2s / 4s delays
            for attempt in range(LLM_MAX_RETRIES):
                try:
                    _sys.stderr.write(f"[DBG] send_completion stream={self.stream} msgs={len(messages)}\n"); _sys.stderr.flush()
                    if self.stream:
                        resp = self.main_model.send_completion(messages, stream=True)
                        _sys.stderr.write("[DBG] got iterator\n"); _sys.stderr.flush()
                        self._stream_response(resp)
                        _sys.stderr.write("[DBG] stream done\n"); _sys.stderr.flush()
                    else:
                        c = self.main_model.simple_send(messages)
                        if c:
                            self.partial_response_content = c; self.multi_response_content = c
                            self.io.print_assistant_output(c)
                        else:
                            self.io.tool_error("LLM returned empty response")
                            self.cur_messages.pop(); return
                    break  # success — exit retry loop
                except Exception as err:
                    if attempt < LLM_MAX_RETRIES - 1:
                        delay = 2 ** attempt  # 1s, 2s
                        self.io.tool_warning(
                            f"LLM error [{self.main_model.name}] "
                            f"(retry {attempt + 1}/3 in {delay}s): {err}"
                        )
                        time.sleep(delay)
                    else:
                        self.cur_messages.pop()
                        raise LLMError(self.main_model.name, str(err))
            # Bail out if tool executor hit the consecutive-error limit
            if self.tool_exec_state.too_many_errors:
                self.io.tool_warning(
                    "Too many consecutive tool errors — stopping tool loop. "
                    "Review the errors above and retry."
                )
                ac = self.partial_response_content
                if ac: self.cur_messages.append(dict(role="assistant", content=ac))
                break
            had = self._process_tool_calls()
            if had:
                from ..tools.parser import parse_xml_tools
                from ..tools.result import TextBlock
                blocks = parse_xml_tools(self.partial_response_content, self.tool_registry)
                text_parts = [b.content.strip() for b in blocks if isinstance(b, TextBlock) and b.content.strip()]
                clean_text = "\n".join(text_parts) if text_parts else "(used tools)"
                self.cur_messages.append(dict(role="assistant", content=clean_text))
                self.partial_response_content = ""; self.multi_response_content = ""
            else:
                ac = self.partial_response_content
                if ac: self.cur_messages.append(dict(role="assistant", content=ac))
                break
        # Run legacy edits once, after the tool-call loop finishes
        self._process_legacy_edits()

        if hasattr(self, "reply_completed") and callable(self.reply_completed):
            self.reply_completed()
        edited = self.tool_exec_state.had_file_edits
        if edited and self.auto_commits and self.repo:
            self.auto_commit()
        self.done_messages.extend(self.cur_messages); self.cur_messages = []
        self.summarize_if_needed()
        self._save_session()

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
            pass  # best-effort — never break the main loop

    def _process_tool_calls(self):
        from ..tools.parser import parse_xml_tools
        from ..tools.result import ToolCall
        if not self.partial_response_content: return False
        blocks = parse_xml_tools(self.partial_response_content, self.tool_registry)
        calls = [b for b in blocks if isinstance(b, ToolCall)]
        if calls:
            self.tool_executor.execute_all(calls)
            return True
        return False

    def _process_legacy_edits(self):
        self.process_response()
        if self.shell_commands:
            for cmd in self.shell_commands:
                from ..tools.handlers.run_shell_handler import RunShellHandler
                h = RunShellHandler()
                h.execute(ToolCall("run_shell", {"command": cmd, "requires_approval": "true"}), self)

    def _trim_context_for_model(self) -> None:
        mt = self.main_model.max_input_tokens
        if mt <= 0: return
        all_msgs = list(self.done_messages) + list(self.cur_messages)
        if self.main_model.token_count(all_msgs) <= mt: return
        ct = self.main_model.token_count(self.cur_messages)
        avail = mt - ct - CONTEXT_RESERVE_TOKENS
        if avail <= 0: return

        # Tier 1: LLM summarization (preserves meaning of old messages)
        if self.summarizer is None:
            try:
                from ..history import ChatSummary
                self.summarizer = ChatSummary(models=[self.main_model], max_tokens=avail)
            except Exception: pass
        if self.summarizer and self.summarizer.too_big(self.done_messages):
            try:
                self.done_messages = self.summarizer.summarize(self.done_messages)
                return
            except Exception:
                pass

        # Tier 2: ContextManager truncation
        self._context_truncate()

    def _context_truncate(self) -> None:
        """Use ContextManager for tiered truncation when summarization is unavailable."""
        if self._context_mgr is None:
            try:
                from ..context_manager import ContextManager
                self._context_mgr = ContextManager(
                    token_counter=self.main_model.token_count,
                    max_input_tokens=self.main_model.max_input_tokens,
                )
            except Exception:
                self._emergency_truncate()
                return
        snap = self._context_mgr.prepare_messages(self.done_messages)
        if snap.truncated:
            self.done_messages = snap.messages
            if self.verbose:
                self.io.tool_output(
                    f"Context: {snap.strategy} truncation removed {snap.deleted_count} messages"
                )

    def _emergency_truncate(self):
        """Last-resort truncation — removes oldest done_messages."""
        keep = self.done_messages[-EMERGENCY_KEEP_MESSAGES:]
        while len(keep) > 1 and keep[0].get("role") != "assistant":
            keep = keep[1:]
        deleted = len(self.done_messages) - len(keep)
        if deleted > 0:
            notice = {
                "role": "user",
                "content": f"[CONTEXT TRUNCATED] {deleted} older messages were removed to stay within the context window."
            }
            self.done_messages = [notice] + keep

    def summarize_if_needed(self):
        if not self.summarizer:
            try:
                from ..history import ChatSummary
                self.summarizer = ChatSummary(models=[self.main_model], max_tokens=4096)
            except Exception: return
        if self.summarizer and self.summarizer.too_big(self.done_messages):
            try: self.done_messages = self.summarizer.summarize(self.done_messages)
            except Exception: pass

    def auto_commit(self):
        if not self.repo: return
        r = self.repo.commit(fnames=None, aider_edits=True, coder=self)
        if r: self.aider_commit_hashes.add(r[0])

    def _stream_response(self, response):
        cc = []
        try:
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    c = chunk.choices[0].delta.content
                    if c:
                        cc.append(c)
                        self.io.print_streaming(c)
            if not hasattr(self.io, "finalize_streaming"):
                self.io.tool_output("")
        except Exception as e:
            self.io.tool_error("Stream: " + str(e))
        self.partial_response_content = "".join(cc)
        if hasattr(self.io, "finalize_streaming"):
            self.io.finalize_streaming(self.partial_response_content)
        self.multi_response_content = self.partial_response_content

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

from ..tools.result import ToolCall
