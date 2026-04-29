import os, sys, time, shutil
from pathlib import Path
from ..io import InputOutput
from ..models import Model, DEFAULT_MODEL_NAME
from .base_prompts import CoderPrompts
from ..commands import Commands, SwitchCoder

all_fences = [("```", "```"), ("````", "````"), ("<source>", "</source>"), ("<code>", "</code>")]

class Coder:
    edit_format = None
    gpt_prompts = CoderPrompts()
    fences = all_fences
    fence = fences[0]

    def __init__(self, main_model, io, fnames=None, verbose=False, stream=True, auto_commits=True, map_tokens=1024):
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
        self.commands = Commands(io, self); self.root = os.getcwd()
        self._first_message = True; self._file_tree = None
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
        from ..tools.prompt_builder import PromptBuilder
        from ..tools.result import ExecutionState
        from ..tools.tools.edit_file import EDIT_FILE_SPEC
        from ..tools.tools.write_file import WRITE_FILE_SPEC
        from ..tools.tools.run_shell import RUN_SHELL_SPEC
        from ..tools.tools.read_file import READ_FILE_SPEC
        from ..tools.tools.search_files import SEARCH_FILES_SPEC
        from ..tools.tools.list_files import LIST_FILES_SPEC
        from ..tools.tools.list_code_defs import LIST_CODE_DEFS_SPEC
        from ..tools.handlers.edit_file_handler import EditFileHandler
        from ..tools.handlers.write_file_handler import WriteFileHandler
        from ..tools.handlers.run_shell_handler import RunShellHandler
        from ..tools.handlers.read_file_handler import ReadFileHandler
        from ..tools.handlers.search_files_handler import SearchFilesHandler
        from ..tools.handlers.list_files_handler import ListFilesHandler
        from ..tools.handlers.list_code_defs_handler import ListCodeDefsHandler
        self.tool_registry = ToolRegistry()
        for spec in [EDIT_FILE_SPEC, WRITE_FILE_SPEC, RUN_SHELL_SPEC, READ_FILE_SPEC,
                     SEARCH_FILES_SPEC, LIST_FILES_SPEC, LIST_CODE_DEFS_SPEC]:
            self.tool_registry.register(spec)
        self.tool_prompt_builder = PromptBuilder(self.tool_registry.get_all())
        self._update_tool_model_info()
        self.tool_coordinator = ToolCoordinator()
        for h in [EditFileHandler(), WriteFileHandler(), RunShellHandler(),
                  ReadFileHandler(), SearchFilesHandler(), ListFilesHandler(), ListCodeDefsHandler()]:
            self.tool_coordinator.register(h)
        self.tool_exec_state = ExecutionState()
        self.tool_executor = ToolExecutor(self.tool_coordinator, self, self.tool_exec_state)

    def _update_tool_model_info(self):
        import platform
        from ..models import MODEL_TOKEN_LIMITS
        model_names = [k for k in MODEL_TOKEN_LIMITS if not k.startswith("machao-")]
        model_names += ["machao-flash", "machao-pro"]
        self.tool_prompt_builder.set_models(model_names, self.main_model.name)
        self.tool_prompt_builder.set_cwd(self.root.replace("\\", "/"))
        cwd = self.root.replace("\\", "/")
        os_name = platform.system()
        if os_name == "Windows":
            hint = "# SYSTEM INFO\n\nWorking directory: " + cwd + "\nYou are on Windows. Use: dir (not ls). Prefer list_files tool.\n"
        else:
            hint = "# SYSTEM INFO\n\nWorking directory: " + cwd + "\nYou are on " + os_name + ". Prefer list_files tool.\n"
        self.tool_prompt_builder.set_os_info(hint)

    def _find_common_root(self, paths):
        if not paths: return os.getcwd()
        return str(Path(os.path.commonpath([Path(p).parent for p in paths])))

    @classmethod
    def create(cls, main_model=None, edit_format=None, io=None, **kwargs):
        if not main_model: main_model = Model(DEFAULT_MODEL_NAME)
        if edit_format is None: edit_format = main_model.edit_format or "whole"
        coder_classes = {"whole": "wholefile_coder.WholeFileCoder", "diff": "editblock_coder.EditBlockCoder",
                         "ask": "ask_coder.AskCoder", "architect": "architect_coder.ArchitectCoder"}
        class_path = coder_classes.get(edit_format)
        if class_path:
            mn, cn = class_path.rsplit(".", 1)
            import importlib
            m = importlib.import_module(f".{mn}", package="aicoder.coders")
            return getattr(m, cn)(main_model, io, **kwargs)
        from .wholefile_coder import WholeFileCoder
        return WholeFileCoder(main_model, io, **kwargs)

    def abs_root_path(self, path):
        if path in self.abs_root_path_cache: return self.abs_root_path_cache[path]
        # 阻止绝对路径穿越工作区
        p = Path(path)
        if p.is_absolute():
            try: p.relative_to(self.root)
            except ValueError:
                raise ValueError(f"Path traversal blocked: {path} is outside workspace {self.root}")
        res = str(Path(self.root) / path); res = str(Path(res).resolve())
        self.abs_root_path_cache[path] = res; return res

    def get_rel_fname(self, fname):
        try: return os.path.relpath(fname, self.root)
        except ValueError: return fname

    def get_inchat_relative_files(self):
        return sorted(self.get_rel_fname(f) for f in self.abs_fnames)

    def get_all_relative_files(self): return self.get_inchat_relative_files()
    def get_addable_relative_files(self): return []

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
                if entry.startswith("."): continue
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

    def format_messages(self):
        messages = []
        main_system = getattr(self.gpt_prompts, "main_system", "")
        system_reminder = getattr(self.gpt_prompts, "system_reminder", "")
        model_name = self.main_model.name.lower() if self.main_model else ""
        if "machao-pro" in model_name:
            from .base_prompts import MACHO_IDENTITY_PRO
            ai_identity = MACHO_IDENTITY_PRO
        elif "machao" in model_name:
            from .base_prompts import MACHO_IDENTITY_FLASH
            ai_identity = MACHO_IDENTITY_FLASH
        else: ai_identity = getattr(self.gpt_prompts, "ai_identity", "")
        system_content = main_system
        if ai_identity: system_content = ai_identity + "\n\n" + system_content
        if system_reminder: system_content += "\n\n" + system_reminder
        tool_docs = self.tool_prompt_builder.generate()
        system_content += "\n\n" + tool_docs
        if system_content: messages.append(dict(role="system", content=system_content))
        for msg in getattr(self.gpt_prompts, "example_messages", []): messages.append(msg)
        messages.extend(self.done_messages)
        repo_map = self.get_repo_map()
        if repo_map:
            messages += [dict(role="user", content=repo_map), dict(role="assistant", content="Ok.")]
        messages.extend(self.get_chat_files_messages())
        messages.extend(self.cur_messages)
        return messages

    def get_chat_files_messages(self):
        chat = []
        cwd = self.root.replace("\\", "/")
        if self.abs_fnames:
            wh = "Working directory: " + cwd + "\n\nYou are in this directory. Files added to chat:"
            fc = wh + "\n\n" + self.gpt_prompts.files_content_prefix + self.get_files_content()
            fr = self.gpt_prompts.files_content_assistant_reply
        else:
            fc = "Working directory: " + cwd + "\n\nNo files added to chat. You CAN explore with list_files, read_file, search_files."
            fr = "Ok."
        if self._first_message:
            self._first_message = False
            parts = []
            ws = self._build_workspace_info()
            if ws: parts.append(ws)

            # 文件树（桌面目录跳过，对照 Cline 的 getDesktopDir 检测）
            if self._file_tree is None:
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                if os.path.abspath(self.root) == os.path.abspath(desktop):
                    parts.append("# Current Working Directory Files\n(Desktop files not shown automatically. Use list_files to explore.)\n")
                else:
                    self._file_tree = self._build_file_tree()
            if self._file_tree: parts.append(self._file_tree)

            tools = self._detect_cli_tools()
            if tools: parts.append(tools)

            # 上下文窗口用量（对照 Cline context window usage）
            max_tokens = self.main_model.max_input_tokens
            cur_tokens = self.main_model.token_count(self.done_messages + self.cur_messages)
            pct = round(cur_tokens / max_tokens * 100) if max_tokens > 0 else 0
            parts.append("# Context Window\n" + str(cur_tokens) + " / " + str(max_tokens) + " tokens (" + str(pct) + "%)\n")

            # 当前时间（对照 Cline current time）
            from datetime import datetime
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            parts.append("# Current Time\n" + now + "\n")

            if parts:
                chat += [dict(role="user", content="\n".join(parts)),
                         dict(role="assistant", content="Ok, I see the project.")]
        if fc: chat += [dict(role="user", content=fc), dict(role="assistant", content=fr)]
        return chat

    def get_repo_map(self):
        if not self.repo: return None
        try: from ..repomap import RepoMap
        except ImportError: return None
        chat_rel = set(self.get_inchat_relative_files())
        other = set(self.repo.get_tracked_files()) - chat_rel
        if not other: return None
        prefix = getattr(self.gpt_prompts, "repo_content_prefix", "")
        rm = RepoMap(map_tokens=self.map_tokens, root=self.root, main_model=self.main_model,
                     io=self.io, repo_content_prefix=prefix, verbose=self.verbose)
        return rm.get_repo_map(chat_files=chat_rel, other_files=other)

    def run(self, with_message=None):
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

    def run_one(self, user_message):
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

    def send_message(self, message):
        if self.repo: self.commit_before_message.append(self.repo.get_head_commit_sha())
        self.cur_messages.append(dict(role="user", content=message))
        for _ in range(5):
            self._trim_context_for_model()
            messages = self.format_messages()
            try:
                if self.stream:
                    resp = self.main_model.send_completion(messages, stream=True)
                    self._stream_response(resp)
                else:
                    c = self.main_model.simple_send(messages)
                    if c:
                        self.partial_response_content = c; self.multi_response_content = c
                        self.io.print_assistant_output(c)
                    else:
                        self.io.tool_error("LLM returned empty response")
                        self.cur_messages.pop(); return
            except Exception as err:
                self.io.tool_error("LLM: " + str(err))
                self.cur_messages.pop(); return
            had = self._process_tool_calls()
            self._process_legacy_edits()
            if had:
                # Strip tool XML from assistant message history for cleaner context
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
        # 架构师模式：回复完成后触发 plan → editor 流程
        if hasattr(self, "reply_completed") and callable(self.reply_completed):
            self.reply_completed()

        edited = self.cur_messages and self.partial_response_content
        if edited and self.auto_commits and self.repo: self.auto_commit()
        self.done_messages.extend(self.cur_messages); self.cur_messages = []
        self.summarize_if_needed()

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

    def _trim_context_for_model(self):
        mt = self.main_model.max_input_tokens
        if mt <= 0: return
        all_msgs = list(self.done_messages) + list(self.cur_messages)
        if self.main_model.token_count(all_msgs) <= mt: return
        ct = self.main_model.token_count(self.cur_messages)
        avail = mt - ct - 512
        if avail <= 0: return
        if self.summarizer is None:
            try:
                from ..history import ChatSummary
                self.summarizer = ChatSummary(models=[self.main_model], max_tokens=avail)
            except Exception: pass
        if self.summarizer and self.summarizer.too_big(self.done_messages):
            try: self.done_messages = self.summarizer.summarize(self.done_messages)
            except Exception: pass

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
                    if c: cc.append(c); self.io.print_streaming(c)
            print()
        except Exception as e: self.io.tool_error("Stream: " + str(e))
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
