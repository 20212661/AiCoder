"""
斜杠命令系统
约定：任何 cmd_xxx 方法自动成为 /xxx 命令
参考 Aider 的 commands.py，简化版
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from .io import InputOutput

if TYPE_CHECKING:
    from .coders.base_coder import Coder


class SwitchCoder(Exception):
    """抛出此异常来切换 Coder（模型/编辑格式变更）"""
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs: dict[str, Any] = kwargs


class Commands:
    """斜杠命令管理器"""

    def __init__(self, io: InputOutput, coder: Coder) -> None:
        self.io: InputOutput = io
        self.coder: Coder = coder

    def is_command(self, inp: str) -> bool:
        """检查输入是否是命令"""
        return bool(inp and inp[0] in "/!")

    def get_commands(self) -> list[str]:
        """获取所有可用命令（内置 + 插件）"""
        commands: list[str] = []
        # 内置命令：通过 cmd_xxx 方法发现
        for attr in dir(self):
            if not attr.startswith("cmd_"):
                continue
            cmd = attr[4:]
            cmd = cmd.replace("_", "-")
            commands.append("/" + cmd)
        # 插件命令：从全局注册表获取
        try:
            from .plugins import plugin_registry
            for name in plugin_registry.get_commands():
                commands.append("/" + name)
        except ImportError:
            pass
        return commands

    def do_run(self, cmd_name: str, args: str) -> Any:
        """执行指定命令（内置优先，回退到插件）"""
        # 1. 尝试内置命令
        method_name = cmd_name.replace("-", "_")
        cmd_method = getattr(self, f"cmd_{method_name}", None)
        if cmd_method:
            return cmd_method(args)
        # 2. 尝试插件命令
        try:
            from .plugins import plugin_registry
            plugin_cmd = plugin_registry.get_commands().get(cmd_name)
            if plugin_cmd:
                return plugin_cmd(self, args)
        except ImportError:
            pass
        self.io.tool_error(f"Unknown command: /{cmd_name}")
        return None

    def matching_commands(self, inp: str) -> Optional[tuple[list[str], str, str]]:
        """前缀匹配命令"""
        words = inp.strip().split()
        if not words:
            return None

        first_word = words[0]
        rest_inp = inp[len(words[0]) :].strip()

        all_commands = self.get_commands()
        matching = [cmd for cmd in all_commands if cmd.startswith(first_word)]
        return matching, first_word, rest_inp

    def run(self, inp: str) -> Any:
        """执行命令入口"""
        if inp.startswith("!"):
            return self.do_run("run", inp[1:])

        res = self.matching_commands(inp)
        if res is None:
            return None
        matching_commands, first_word, rest_inp = res
        if len(matching_commands) == 1:
            command = matching_commands[0][1:]
            return self.do_run(command, rest_inp)
        elif first_word in matching_commands:
            command = first_word[1:]
            return self.do_run(command, rest_inp)
        elif len(matching_commands) > 1:
            self.io.tool_error(f"Ambiguous command: {', '.join(matching_commands)}")
        else:
            self.io.tool_error(f"Unknown command: {first_word}")
        return None

    # ---- 命令实现 ----

    def cmd_help(self, args: str) -> None:
        """显示可用命令列表"""
        self.io.tool_output("Available commands:")
        for attr in sorted(dir(self)):
            if not attr.startswith("cmd_"):
                continue
            cmd = attr[4:].replace("_", "-")
            doc = getattr(self, attr).__doc__ or ""
            doc = doc.strip().split("\n")[0]
            self.io.tool_output(f"  /{cmd:<15} {doc}")
        # 显示插件命令
        try:
            from .plugins import plugin_registry
            plugin_cmds = plugin_registry.get_commands()
            if plugin_cmds:
                self.io.tool_output("Plugin commands:")
                for name, func in sorted(plugin_cmds.items()):
                    doc = (func.__doc__ or "").strip().split("\n")[0]
                    self.io.tool_output(f"  /{name:<15} {doc}")
        except ImportError:
            pass
        self.io.tool_output("  !<command>        Run a shell command")

    def cmd_add(self, args: str) -> None:
        """添加文件到聊天中"""
        filenames = _parse_quoted_filenames(args)
        for word in filenames:
            if Path(word).is_absolute():
                fname = Path(word)
            else:
                fname = Path(self.coder.root) / word

            if fname.exists():
                if fname.is_file():
                    abs_path = str(fname.resolve())
                    if abs_path in self.coder.abs_fnames:
                        self.io.tool_error(f"{word} is already in the chat")
                        continue
                    self.coder.abs_fnames.add(abs_path)
                    self.io.tool_output(f"Added {word} to the chat")
                    continue
                # 目录 → 递归展开（上限 200 个文件）
                added = 0
                for f in sorted(fname.rglob("*")):
                    if not f.is_file():
                        continue
                    abs_path = str(f.resolve())
                    if abs_path not in self.coder.abs_fnames:
                        self.coder.abs_fnames.add(abs_path)
                        added += 1
                        self.io.tool_output(
                            f"Added {f.relative_to(self.coder.root)} to the chat"
                        )
                        if added >= 200:
                            self.io.tool_warning(f"Reached 200 file limit. Use /add on subdirectories for more.")
                            break
                continue

            # glob 匹配
            if "*" in str(fname) or "?" in str(fname):
                matches = glob.glob(str(fname), recursive=True)
                if matches:
                    for m in matches:
                        abs_path = str(Path(m).resolve())
                        if abs_path not in self.coder.abs_fnames:
                            self.coder.abs_fnames.add(abs_path)
                            self.io.tool_output(f"Added {m} to the chat")
                else:
                    self.io.tool_error(f"No files matched '{word}'")
                continue

            # 新文件
            if self.io.confirm_ask(f"No files matched '{word}'. Create {fname}?"):
                try:
                    fname.parent.mkdir(parents=True, exist_ok=True)
                    fname.touch()
                    abs_path = str(fname.resolve())
                    self.coder.abs_fnames.add(abs_path)
                    self.io.tool_output(f"Created and added {word}")
                except OSError as e:
                    self.io.tool_error(f"Error creating file: {e}")

    def cmd_drop(self, args: str = "") -> None:
        """从聊天中移除文件"""
        if not args.strip():
            self.io.tool_output("Dropping all files from the chat session.")
            self.coder.abs_fnames.clear()
            self.coder.abs_read_only_fnames.clear()
            return

        filenames = _parse_quoted_filenames(args)
        for word in filenames:
            matched = False
            to_remove: set[str] = set()
            for f in self.coder.abs_fnames:
                if word in f or word in self.coder.get_rel_fname(f):
                    to_remove.add(f)
                    matched = True

            for f in to_remove:
                self.coder.abs_fnames.discard(f)
                self.io.tool_output(f"Removed {self.coder.get_rel_fname(f)} from the chat")

            if not matched:
                self.io.tool_error(f"No files matched '{word}'")

    def cmd_model(self, args: str) -> None:
        """切换 LLM 模型"""
        from .models import Model
        model_name = args.strip()
        if not model_name:
            self.io.tool_output(f"Current model: {self.coder.main_model.name}")
            return

        model = Model(model_name)
        # 防止切换到同名模型导致无限循环
        if model_name == self.coder.main_model.name:
            self.io.tool_output(f"Already using {model_name}")
            return

        old_format = self.coder.main_model.edit_format
        current_format = self.coder.edit_format

        new_format = current_format
        if current_format == old_format:
            new_format = model.edit_format

        raise SwitchCoder(main_model=model, edit_format=new_format)

    def cmd_plan(self, args: str) -> None:
        """切换到 Plan 模式（只读探索）"""
        self.coder.tool_executor.set_mode("plan")
        self.coder._update_tool_model_info()
        self.io.tool_output(
            "Switched to PLAN MODE. Only read-only tools and inspection shell commands are enabled."
        )

    def cmd_act(self, args: str) -> None:
        """切换到 Act 模式（全部工具可用）"""
        self.coder.tool_executor.set_mode("act")
        self.coder._update_tool_model_info()
        self.io.tool_output(
            "Switched to ACT MODE. Implementation tools and routine shell actions are enabled."
        )

    def cmd_undo(self, args: str) -> Optional[str]:
        """撤销上次 AI 提交"""
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return None

        last_commit = self.coder.repo.get_head_commit()
        if not last_commit or not last_commit.parents:
            self.io.tool_error("This is the first commit. Cannot undo.")
            return None

        last_commit_hash = self.coder.repo.get_head_commit_sha(short=True)
        last_commit_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        last_commit_message = (last_commit_message.splitlines() or [""])[0]

        if last_commit_hash not in self.coder.aider_commit_hashes:
            self.io.tool_error("The last commit was not made by aiCoder in this session.")
            self.io.tool_output(
                "You could try `/git reset --hard HEAD^` but be aware this is destructive!"
            )
            return None

        if len(last_commit.parents) > 1:
            self.io.tool_error(f"Commit {last_commit.hexsha} has multiple parents, can't undo.")
            return None

        prev_commit = last_commit.parents[0]
        changed_files = [item.a_path for item in last_commit.diff(prev_commit)]

        # 检查是否有未提交的更改
        for fname in changed_files:
            if self.coder.repo.repo.is_dirty(path=fname):
                self.io.tool_error(f"File {fname} has uncommitted changes. Stash them first.")
                return None

        # 恢复文件（新增文件在 HEAD~1 中不存在，跳过）
        for file_path in changed_files:
            try:
                self.coder.repo.repo.git.checkout("HEAD~1", file_path)
            except Exception:
                try:
                    self.coder.repo.repo.git.rm(file_path)
                except Exception:
                    pass

        # 软重置
        self.coder.repo.repo.git.reset("--soft", "HEAD~1")

        self.coder.aider_commit_hashes.discard(last_commit_hash)
        current_hash = self.coder.repo.get_head_commit_sha(short=True)
        current_msg = self.coder.repo.get_head_commit_message("").strip()
        current_msg = (current_msg.splitlines() or [""])[0]

        self.io.tool_output(f"Removed: {last_commit_hash} {last_commit_message}")
        self.io.tool_output(f"Now at:  {current_hash} {current_msg}")

        from .prompts import undo_command_reply
        return undo_command_reply

    def cmd_diff(self, args: str = "") -> None:
        """显示上次消息后的更改"""
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        current_head = self.coder.repo.get_head_commit_sha()
        if current_head is None:
            self.io.tool_error("Unable to get current commit.")
            return

        if len(self.coder.commit_before_message) < 2:
            commit_before_message = current_head + "^"
        else:
            commit_before_message = self.coder.commit_before_message[-2]

        if not commit_before_message or commit_before_message == current_head:
            self.io.tool_warning("No changes to display since the last message.")
            return

        self.io.tool_output(f"Diff since {commit_before_message[:7]}...")
        try:
            diff = self.coder.repo.diff_commits(False, commit_before_message, "HEAD")
            if diff:
                self.io.tool_output(diff)
            else:
                self.io.tool_output("No changes.")
        except Exception as e:
            self.io.tool_error(f"Unable to get diff: {e}")

    def cmd_commit(self, args: Optional[str] = None) -> None:
        """手动提交更改"""
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        if not self.coder.repo.is_dirty():
            self.io.tool_warning("No changes to commit.")
            return

        message = args.strip() if args else None
        result = self.coder.repo.commit(message=message, aider_edits=False, coder=self.coder)
        if result:
            self.coder.aider_commit_hashes.add(result[0])

    def cmd_clear(self, args: str) -> None:
        """清空聊天历史"""
        self.coder.done_messages = []
        self.coder.cur_messages = []
        self.io.tool_output("Chat history cleared.")

    def cmd_sessions(self, args: str) -> None:
        """列出所有历史会话"""
        from .session import list_sessions, session_count
        sessions = list_sessions()
        if not sessions:
            self.io.tool_output("No saved sessions.")
            return
        self.io.tool_output(f"{session_count()} sessions found:\n")
        for s in sessions[:20]:
            sid = s.get("session_id", "")[:12]
            model = s.get("model_name", "?")
            count = s.get("message_count", 0)
            first = (s.get("first_message", "") or "")[:50]
            self.io.tool_output(f"  {sid}  {model}  [{count} msgs]  {first}")
        count = session_count()
        if count > 20:
            self.io.tool_output(f"  ... and {count - 20} more. Use --list-sessions for full list.")

    def cmd_resume(self, args: str) -> None:
        """恢复之前的会话 /resume <session_id>"""
        sid = args.strip()
        if not sid:
            self.io.tool_error("Usage: /resume <session_id>")
            return
        from .session import load_session
        loaded = load_session(sid)
        if not loaded:
            self.io.tool_error(f"Session not found: {sid}")
            return
        meta, done, cur = loaded
        self.coder.done_messages = done
        self.coder.cur_messages = cur
        self.coder.session_id = meta.session_id
        self.coder._first_user_message = meta.first_message
        self.io.tool_output(f"Resumed session: {sid} ({meta.message_count} messages)")

    def cmd_save(self, args: str) -> None:
        """手动保存当前会话"""
        if not self.coder.session_id:
            self.io.tool_error("Session saving is disabled (--no-save).")
            return
        self.coder._save_session()
        self.io.tool_output(f"Session saved: {self.coder.session_id}")

    def cmd_yolo(self, args: str) -> None:
        """切换 YOLO 模式（自动批准所有操作）"""
        if self.coder._approval is None:
            self.io.tool_error("Approval system not available.")
            return
        current = self.coder._approval.settings.yolo
        self.coder._approval.settings.yolo = not current
        state = "ON" if self.coder._approval.settings.yolo else "OFF"
        self.io.tool_output(f"YOLO mode: {state}")

    def cmd_sniff(self, args: str) -> None:
        """嗅探模式（只读调查，识别构石痕迹，追踪异味来源）"""
        self.coder.tool_executor.set_mode("sniff")
        self.coder._update_tool_model_info()
        self.io.tool_output(
            "已进入 SNIFF 嗅探模式。\n"
            "  - 当前任务：检查发酵区结构，识别构石痕迹，追踪异味来源与污染扩散路径。\n"
            "  - 本模式严格只读，不进行任何文件修改或副作用命令执行。\n"
            "  - 输出将采用「嗅探报告」格式。\n"
            "  - 若需要整理实施方案，请切换 /plan；若需要直接修改，请切换 /act。"
        )

    def cmd_approval(self, args: str) -> None:
        """显示/修改自动批准设置。用法: /approval [category on|off]"""
        if self.coder._approval is None:
            self.io.tool_error("Approval system not available.")
            return
        s = self.coder._approval.settings
        parts = args.strip().split()
        if len(parts) == 2:
            cat, state = parts
            state = state.lower()
            if hasattr(s, cat) and isinstance(getattr(s, cat), bool):
                setattr(s, cat, state in ("on", "true", "yes", "1"))
                from .approval import save_approval_settings
                save_approval_settings(s)
                self.io.tool_output(f"  {cat} = {getattr(s, cat)}")
                return
            self.io.tool_error(f"Unknown setting: {cat}")
            return
        # Display current settings
        lines = ["Auto-approval settings:"]
        for name in ["yolo", "auto_approve_all", "read_files", "edit_files",
                      "execute_safe_cmds", "execute_all_cmds", "list_files",
                      "search_files", "list_code_defs", "block_dangerous_cmds"]:
            val = "ON" if getattr(s, name, False) else "OFF"
            lines.append(f"  {name:<22} {val}")
        self.io.tool_output("\n".join(lines))

    def cmd_safe(self, args: str) -> None:
        """检查一个命令是否在安全列表中 /safe <command>"""
        cmd = args.strip()
        if not cmd:
            self.io.tool_output("Usage: /safe <command>")
            return
        if self.coder._approval is None:
            self.io.tool_error("Approval system not available.")
            return
        is_safe = self.coder._approval.is_command_safe(cmd)
        is_dangerous, warning = self.coder._approval.is_command_dangerous(cmd)
        if is_dangerous:
            self.io.tool_error(f"DANGEROUS: {warning}")
        elif is_safe:
            self.io.tool_output(f"SAFE: {cmd}")
        else:
            self.io.tool_output(f"UNKNOWN safety: {cmd} (will ask for approval)")

    def cmd_git(self, args: str) -> None:
        """运行 git 命令"""
        if not args.strip():
            return
        command = f"git {args}"
        self._run_via_tool_system(command)

    def cmd_run(self, args: str) -> None:
        """运行 shell 命令"""
        if not args.strip():
            return
        self._run_via_tool_system(args)

    def _run_via_tool_system(self, command: str) -> None:
        """通过工具系统执行 shell 命令，统一走审批/超时/结果处理链。"""
        from .tools.result import ToolCall
        tool_call = ToolCall("run_shell", {"command": command})
        result = self.coder.tool_executor.execute(tool_call)
        if result.success:
            output = result.output.strip()
            if output:
                self.io.tool_output(output)
        else:
            if result.rejected:
                self.io.tool_warning(f"Command rejected: {command[:200]}")
            else:
                self.io.tool_error(result.error or "Command failed")

    def cmd_ls(self, args: str) -> None:
        """列出聊天中的文件"""
        chat_files = self.coder.get_inchat_relative_files()
        if chat_files:
            self.io.tool_output("Chat files:")
            for f in chat_files:
                self.io.tool_output(f"  {f}")
        else:
            self.io.tool_output("No files in chat. Use /add to add files.")

    def cmd_map(self, args: str) -> None:
        """显示仓库地图"""
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        tracked = self.coder.repo.get_tracked_files()
        chat_files = set(self.coder.get_inchat_relative_files())

        self.io.tool_output("Repository files:")
        for f in sorted(tracked):
            marker = " [chat]" if f in chat_files else ""
            self.io.tool_output(f"  {f}{marker}")


def _parse_quoted_filenames(args: str) -> list[str]:
    """解析空格/引号分隔的文件名列表"""
    if not args:
        return []

    filenames: list[str] = []
    current = ""
    in_quotes = False
    quote_char: Optional[str] = None

    for char in args:
        if char in ('"', "'") and not in_quotes:
            in_quotes = True
            quote_char = char
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
        elif char == " " and not in_quotes:
            if current:
                filenames.append(current)
            current = ""
        else:
            current += char

    if current:
        filenames.append(current)

    return filenames
