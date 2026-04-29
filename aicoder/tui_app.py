"""
AiCoder Textual TUI - Phosphor Green CRT 终端界面
"""
import asyncio
import queue
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.app import App
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Input, RichLog, Static, SelectionList

from . import __version__
from .commands import SwitchCoder
from .message_pipeline import UiEvent, transform_events


class TuiIO:
    """同步 Coder IO 与异步 TUI 事件循环之间的桥梁"""

    def __init__(self, app):
        self._app = app
        self.yes = True
        self._input_queue = queue.Queue()
        self._stream_event_id = None

    def _post(self, coro):
        loop = self._app._loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop)

    def tool_output(self, msg="", bold=False):
        if msg:
            text = str(msg)
            lines = text.splitlines()
            if len(lines) > 6:
                preview = "\n".join(lines[:3]) + f"\n  … ({len(lines)} lines)"
                self._post(self._app.add_message(preview, "tool"))
            else:
                self._post(self._app.add_message(text, "tool"))

    def tool_error(self, msg=""):
        if msg:
            self._post(self._app.add_message(str(msg), "error"))

    def tool_warning(self, msg=""):
        if msg:
            self._post(self._app.add_message(str(msg), "warning"))

    def tool_call_started(self, tool_name, params=None):
        self._post(self._app.add_tool_event("start", tool_name, params or {}))

    def tool_call_finished(self, result, params=None):
        self._post(self._app.finish_tool_event(result, params or {}))

    def print_assistant_output(self, content):
        if not content:
            return
        thinking, clean = self._split_thinking(self._clean_assistant_text(content))
        if thinking:
            self._post(self._app.add_message(thinking, "thinking"))
        if clean:
            self._post(self._app.add_message(clean, "assistant"))

    def print_streaming(self, chunk):
        if not chunk:
            return
        if self._stream_event_id is None:
            self._stream_event_id = "assistant-stream-" + uuid.uuid4().hex
        self._post(self._app.update_partial_message(self._stream_event_id, chunk, "assistant"))

    def finalize_streaming(self, final_text):
        if self._stream_event_id is not None:
            thinking, clean = self._split_thinking(self._clean_assistant_text(final_text))
            if thinking:
                self._post(self._app.add_message(thinking, "thinking"))
            self._post(self._app.finalize_partial_message(self._stream_event_id, clean, "assistant"))
            self._stream_event_id = None

    def _clean_assistant_text(self, content):
        _TOOL_NAMES = "list_files|search_files|read_file|edit_file|write_file|run_shell|list_code_defs"
        clean = re.sub(r'<(?:' + _TOOL_NAMES + r')(?:\s[^>]*)?/>', '', content)
        clean = re.sub(r'<(' + _TOOL_NAMES + r')(?:\s[^>]*)?>.*?</\1>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'</?(?:path|regex|file_pattern|recursive|command|requires_approval|content|file_path|old_text|new_text|line_number|start_line|end_line|search|replace)>', '', clean)
        return clean.strip()

    def _split_thinking(self, content):
        match = re.search(r"<think>(.*?)</think>", content, flags=re.DOTALL)
        if not match:
            return "", content
        thinking = match.group(1).strip()
        clean = (content[:match.start()] + content[match.end():]).strip()
        return thinking, clean

    def confirm_ask(self, question, default="y"):
        return True

    def get_input(self, *args, **kwargs):
        try:
            self._post(self._app.add_message("AWAITING INPUT...", "system"))
            result = self._input_queue.get(timeout=300)
            return result
        except queue.Empty:
            self.tool_warning("INPUT TIMEOUT")
            return ""

    def submit_input(self, text):
        self._input_queue.put(text)

    def user_input(self, msg, log_only=True):
        pass

    def read_text(self, filename):
        try:
            with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None

    def write_text(self, filename, content):
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)


class AiCoderTUI(App):
    """AiCoder Textual TUI"""

    TITLE = "AICODER"

    CSS = """
    Screen {
        layout: vertical;
        background: #000d00;
    }
    #status-bar {
        height: 1;
        background: #001600;
        color: #00cc00;
        padding: 0 1;
        text-style: bold;
    }
    #chat-panel {
        height: 1fr;
        border: solid #009900;
        background: #000d00;
        padding: 0 1;
        overflow-y: auto;
    }
    #chat-panel:focus {
        text-style: bold;
    }
    #input-container {
        height: 3;
        border-top: heavy #009900;
        background: #001600;
        padding: 0 1;
    }
    #input-prefix {
        width: 2;
        content-align: left middle;
        color: #00ff00;
        text-style: bold;
    }
    #message-input {
        width: 1fr;
        border: none;
        background: #001600;
        color: #00ff00;
    }
    #message-input:focus {
        border: none;
    }
    #cmd-popup {
        display: none;
        height: auto;
        max-height: 10;
        background: #001600;
        border: solid #00ff00;
        padding: 0 1;
        margin: 0 1;
        overflow-y: auto;
    }
    #cmd-popup.visible {
        display: block;
    }
    #cmd-popup OptionList {
        background: #001600;
        color: #00ff00;
    }
    #cmd-popup OptionList:focus {
        background: #001600;
    }
    #cmd-popup OptionList > .option-list--option {
        padding: 1 2;
        color: #00cc00;
    }
    #cmd-popup OptionList > .option-list--option.highlight {
        background: #009900;
        color: #000d00;
    }
    #cmd-popup OptionList > .option-list--option:hover {
        background: #009900;
        color: #000d00;
    }
    #footer {
        height: 1;
        background: #001600;
        color: #009900;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "handle_ctrl_c", "INTERRUPT/COPY", show=True),
        Binding("ctrl+shift+c", "copy_lines", "COPY", show=True),
        Binding("ctrl+q", "quit", "QUIT", show=True),
        Binding("ctrl+l", "clear_screen", "CLEAR", show=True),
        Binding("ctrl+p", "focus_input", "FOCUS", show=True),
        Binding("escape", "hide_popup", "", show=False),
        Binding("tab", "select_popup", "", show=False),
        Binding("up", "popup_up", "", show=False),
        Binding("down", "popup_down", "", show=False),
    ]

    def __init__(self, coder, git_repo=None):
        super().__init__()
        self._coder = coder
        self._git_repo = git_repo
        self._loop = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="coder")
        self._processing = False
        self._text_buffer = []
        self._ui_events = []
        self._popup_visible = False
        self._popup_index = 0
        self._popup_mode = "command"
        self._popup_items = []
        self._model_names = []
        self._all_commands = []
        self._event_seq = 0

    def compose(self):
        yield Static(id="status-bar")
        yield RichLog(id="chat-panel", highlight=True, markup=True, wrap=True)
        with Container(id="cmd-popup"):
            yield Static(id="cmd-popup-content")
        with Horizontal(id="input-container"):
            yield Static("> ", id="input-prefix")
            yield Input(id="message-input", placeholder="ENTER COMMAND...")
        yield Static(id="footer")

    def on_mount(self):
        self._loop = asyncio.get_event_loop()
        tui_io = TuiIO(self)
        self._coder.io = tui_io
        self._coder.commands.io = tui_io
        if self._git_repo:
            self._git_repo.io = tui_io
        self._coder.stream = True
        self._all_commands = self._coder.commands.get_commands()
        self._update_status()
        self._update_footer()
        self._refresh_chat_view()
        self.query_one("#message-input", Input).focus()

    def _display_boot_header(self):
        ver = __version__
        return [
            "=" * 38,
            "  AICODER SYSTEM v" + ver,
            "=" * 38,
            "",
        ]

    def _next_event_id(self):
        self._event_seq += 1
        return f"evt-{self._event_seq}"

    async def add_message(self, content, msg_type="system"):
        self._ui_events.append(
            UiEvent(
                event_id=self._next_event_id(),
                kind="message",
                content=content,
                msg_type=msg_type,
            )
        )
        self._refresh_chat_view()

    async def add_tool_event(self, phase, tool_name, params=None):
        self._ui_events.append(
            UiEvent(
                event_id=self._next_event_id(),
                kind="tool",
                tool_name=tool_name,
                phase=phase,
                params=dict(params or {}),
                partial=(phase == "start"),
            )
        )
        self._refresh_chat_view()

    async def finish_tool_event(self, result, params=None):
        self._ui_events.append(
            UiEvent(
                event_id=self._next_event_id(),
                kind="tool",
                tool_name=result.tool_name,
                phase="finish",
                params=dict(params or {}),
                success=result.success,
                output=result.output,
                error=result.error,
                meta=dict(getattr(result, "meta", {}) or {}),
            )
        )
        self._refresh_chat_view()

    async def update_partial_message(self, event_id, chunk, msg_type="assistant"):
        for event in reversed(self._ui_events):
            if event.event_id == event_id:
                event.content += chunk
                event.partial = True
                self._refresh_chat_view()
                return
        self._ui_events.append(
            UiEvent(
                event_id=event_id,
                kind="message",
                content=chunk,
                msg_type=msg_type,
                partial=True,
            )
        )
        self._refresh_chat_view()

    async def finalize_partial_message(self, event_id, final_text, msg_type="assistant"):
        for event in reversed(self._ui_events):
            if event.event_id == event_id:
                event.content = final_text
                event.partial = False
                self._refresh_chat_view()
                return
        self._ui_events.append(
            UiEvent(
                event_id=event_id,
                kind="message",
                content=final_text,
                msg_type=msg_type,
                partial=False,
            )
        )
        self._refresh_chat_view()

    def _style_message(self, content, msg_type):
        """按消息类型应用 Rich 标记样式 — 对照 Cline 的 ChatRow 分派"""
        if msg_type == "user":
            return "[bold #00ff00]▸[/] " + content
        elif msg_type == "assistant":
            return "[#00cc00]│[/] " + content
        elif msg_type == "error":
            lines = content.splitlines()
            if len(lines) <= 2:
                return "[bold #ff1493]✗[/] " + content
            return "[bold #ff1493]✗[/] " + lines[0] + f"\n  … ({len(lines)} lines)"
        elif msg_type == "warning":
            return "[#ffb000]⚠[/] " + content
        elif msg_type == "tool":
            return "[dim #006600]▸[/] " + content
        elif msg_type == "info":
            return "[dim #008800]·[/] " + content
        return content

    def _refresh_chat_view(self):
        chat = self.query_one("#chat-panel", RichLog)
        should_scroll = chat.is_vertical_scroll_end
        chat.clear()
        self._text_buffer.clear()
        self._update_footer()

        for line in self._display_boot_header():
            chat.write(line)
            self._text_buffer.append(line)

        for node in transform_events(self._ui_events):
            renderable, plain_text = self._render_node(node)
            chat.write(renderable)
            self._text_buffer.append(plain_text)

        if should_scroll:
            chat.scroll_end(animate=False)

    def _render_node(self, node):
        if node.kind == "message":
            if node.msg_type == "assistant":
                return self._render_markdown_message(node.content, node.partial)
            if node.msg_type == "thinking":
                return self._render_thinking(node.content, node.partial)
            styled = self._style_message(node.content, node.msg_type)
            return styled, node.content

        if node.kind == "tool_group":
            body = "\n".join(f"  {item}" for item in node.items)
            panel = Panel(body, title=node.title, border_style="#00aa00", padding=(0, 1))
            return panel, node.title + "\n" + body

        if node.kind == "command":
            return self._render_command(node)

        if node.kind == "diff":
            return self._render_diff(node)

        if node.kind == "tool_status":
            style = "#ffb000" if node.partial else "#888888"
            return Panel(node.title, border_style=style, title="Working"), node.title

        if node.kind == "tool":
            panel = Panel(node.body or "", title=node.title, border_style="#00cccc", padding=(0, 1))
            return panel, node.title + ("\n" + node.body if node.body else "")

        return node.content, node.content

    def _strip_markup(self, text):
        return re.sub(r"\[[^\]]+\]", "", text)

    def _render_markdown_message(self, content, partial=False):
        header = Text("Assistant", style="bold #00cc00")
        if partial:
            header.append("  streaming...", style="italic #88ff88")
        group = Group(header, Markdown(content or ""))
        return Panel(group, border_style="#00cc00", padding=(0, 1)), content

    def _render_thinking(self, content, partial=False):
        title = "Thinking..." if partial else "Thinking"
        group = Group(Text(title, style="bold #ffaa00"), Markdown(content or ""))
        return Panel(group, border_style="#ffaa00", padding=(0, 1)), content

    def _render_command(self, node):
        status = "RUNNING" if node.partial else "DONE"
        status_style = "#ffcc00" if node.partial else "#66ccff"
        header = Text(f"{status}  {node.title}", style=f"bold {status_style}")
        body = Syntax(node.body or "(no output)", "bash", theme="monokai", line_numbers=False, word_wrap=True)
        return Panel(Group(header, body), border_style=status_style, padding=(0, 1)), node.title + "\n" + (node.body or "")

    def _render_diff(self, node):
        diff_text = node.body or node.meta.get("content", "")
        syntax = Syntax(diff_text or "(no diff)", "diff", theme="monokai", line_numbers=False, word_wrap=False)
        title = node.title + ("  partial" if node.partial else "")
        return Panel(syntax, title=title, border_style="#33aa55", padding=(0, 1)), node.title + "\n" + diff_text

    async def append_stream_chunk(self, chunk):
        pass

    def _update_status(self):
        bar = self.query_one("#status-bar", Static)
        m = self._coder.main_model.name if self._coder.main_model else "UNKNOWN"
        branch = ""
        if self._git_repo:
            try:
                branch = " | BRANCH: " + self._git_repo.repo.active_branch.name.upper()
            except Exception:
                branch = " | GIT: OK"
        fcnt = len(self._coder.get_inchat_relative_files())
        if self._processing:
            st = "[bold #ffb000]● PROCESSING[/]"
        else:
            st = "[#00ff00]● ONLINE[/]"
        bar.update(" MODEL: " + m.upper() + branch + " | FILES: " + str(fcnt) + " | " + st)

    def _update_footer(self):
        f = self.query_one("#footer", Static)
        f.update(self._footer_text())

    def _footer_text(self):
        if self._processing:
            return " CANCEL: CTRL+C | COPY: CTRL+SHIFT+C | PASTE: RIGHT-CLICK | /HELP"
        if self._ui_events:
            last = self._ui_events[-1]
            if last.kind == "tool" and last.phase == "start":
                return " TOOL RUNNING | CANCEL: CTRL+C | COPY: CTRL+SHIFT+C | /HELP"
            if last.kind == "message" and last.msg_type == "thinking":
                return " THINKING | SEND: CTRL+ENTER | COPY: CTRL+SHIFT+C | /HELP"
        return " SEND: CTRL+ENTER | COPY: CTRL+SHIFT+C | PASTE: RIGHT-CLICK | /HELP"

    # ── 命令弹窗 ──

    def _show_popup(self, matches):
        popup = self.query_one("#cmd-popup", Container)
        content = self.query_one("#cmd-popup-content", Static)
        self._popup_index = 0
        highlight = list(matches)
        if self._popup_index < len(highlight):
            highlight[self._popup_index] = "> " + highlight[self._popup_index]
        content.update("\n".join(highlight))
        popup.add_class("visible")
        self._popup_visible = True

    def _hide_popup(self):
        popup = self.query_one("#cmd-popup", Container)
        popup.remove_class("visible")
        self._popup_visible = False
        self._update_footer()

    def _refresh_popup(self, matches):
        if not matches:
            self._hide_popup()
            return
        content = self.query_one("#cmd-popup-content", Static)
        self._popup_items = list(matches)
        self._popup_index = min(self._popup_index, len(self._popup_items) - 1)
        highlight = list(self._popup_items)
        highlight[self._popup_index] = "> " + highlight[self._popup_index]
        content.update("\n".join(highlight))

    async def action_hide_popup(self):
        self._hide_popup()

    async def action_select_popup(self):
        """Tab/Enter: 选中当前弹窗项"""
        if not self._popup_visible:
            return
        popup_mode = getattr(self, "_popup_mode", "command")
        if popup_mode == "model":
            self._select_model()
        else:
            self._select_command()

    def _select_command(self):
        lines = getattr(self, "_popup_items", [])
        if lines and self._popup_index < len(lines):
            cmd = lines[self._popup_index].replace("> ", "").strip()
            inp = self.query_one("#message-input", Input)
            inp.value = cmd + " "
            inp.cursor_position = len(inp.value)
        self._hide_popup()
        self.query_one("#message-input", Input).focus()

    def _select_model(self):
        self._hide_popup()
        if hasattr(self, "_model_names") and self._popup_index < len(self._model_names):
            model_name = self._model_names[self._popup_index]
            inp = self.query_one("#message-input", Input)
            inp.clear()
            inp.focus()
            from .commands import SwitchCoder
            try:
                self._coder.commands.cmd_model(model_name)
                self._update_status()
            except SwitchCoder as sc:
                asyncio.run_coroutine_threadsafe(self._switch_coder(sc), self._loop)

    async def action_popup_up(self):
        if not self._popup_visible:
            return
        popup_mode = getattr(self, "_popup_mode", "command")
        if popup_mode == "model":
            max_idx = len(getattr(self, "_model_names", [])) - 1
            self._popup_index = max(0, self._popup_index - 1)
            self._refresh_model_popup()
            return
        inp = self.query_one("#message-input", Input)
        text = inp.value.strip()
        matches = self._get_matches(text)
        if matches:
            self._popup_index = max(0, self._popup_index - 1)
            self._refresh_popup(matches)

    async def action_popup_down(self):
        if not self._popup_visible:
            return
        popup_mode = getattr(self, "_popup_mode", "command")
        if popup_mode == "model":
            max_idx = len(getattr(self, "_model_names", [])) - 1
            self._popup_index = min(max_idx, self._popup_index + 1)
            self._refresh_model_popup()
            return
        inp = self.query_one("#message-input", Input)
        text = inp.value.strip()
        matches = self._get_matches(text)
        if matches:
            self._popup_index = min(len(matches) - 1, self._popup_index + 1)
            self._refresh_popup(matches)

    def _refresh_model_popup(self):
        from .models import MODEL_TOKEN_LIMITS
        content = self.query_one("#cmd-popup-content", Static)
        current = self._coder.main_model.name if self._coder.main_model else ""
        self._popup_items = []
        for i, name in enumerate(self._model_names):
            info = MODEL_TOKEN_LIMITS[name]
            prefix = ">" if i == self._popup_index else " "
            if name == current:
                prefix = "*" if i != self._popup_index else ">*"
            self._popup_items.append(f"{prefix} {name}  ({info['max_input_tokens']//1000}K context)")
        content.update("\n".join(self._popup_items))

    def _get_matches(self, text):
        res = self._coder.commands.matching_commands(text)
        if res:
            cmds, _, _ = res
            return cmds
        return []

    def on_input_changed(self, event):
        text = event.value.strip()
        # /model 无参数 → 显示模型选择弹窗
        if text == "/model":
            self._show_model_popup()
            return
        if text.startswith("/"):
            matches = self._get_matches(text)
            if matches:
                self._show_popup(matches)
            else:
                self._hide_popup()
        elif self._popup_visible:
            self._hide_popup()

    def _show_model_popup(self):
        from .models import MODEL_TOKEN_LIMITS
        popup = self.query_one("#cmd-popup", Container)
        content = self.query_one("#cmd-popup-content", Static)
        self._model_names = sorted(MODEL_TOKEN_LIMITS.keys())
        self._popup_items = []
        current = self._coder.main_model.name if self._coder.main_model else ""
        for i, name in enumerate(self._model_names):
            info = MODEL_TOKEN_LIMITS[name]
            marker = "*" if name == current else " "
            self._popup_items.append(f"{marker} {name}  ({info['max_input_tokens']//1000}K context)")
        self._popup_index = 0
        highlight = list(self._popup_items)
        highlight[self._popup_index] = highlight[self._popup_index].replace(" ", ">", 1)
        content.update("\n".join(highlight))
        popup.add_class("visible")
        self._popup_visible = True
        self._popup_mode = "model"

    def _show_popup(self, matches):
        self._popup_mode = "command"
        popup = self.query_one("#cmd-popup", Container)
        content = self.query_one("#cmd-popup-content", Static)
        self._popup_index = 0
        self._popup_items = list(matches)
        highlight = list(self._popup_items)
        if self._popup_index < len(highlight):
            highlight[self._popup_index] = "> " + highlight[self._popup_index]
        content.update("\n".join(highlight))
        popup.add_class("visible")
        self._popup_visible = True

    # ── 输入处理 ──

    def on_paste(self, event: events.Paste) -> None:
        """Route terminal paste events to the command input."""
        inp = self.query_one("#message-input", Input)
        inp.focus()
        inp.insert_text_at_cursor(event.text)
        event.stop()

    async def on_input_submitted(self, event):
        if self._popup_visible:
            await self.action_select_popup()
            return
        self._hide_popup()
        content = event.value.strip()
        if not content:
            return
        event.input.clear()
        # 分隔上轮对话
        chat = self.query_one("#chat-panel", RichLog)
        chat.write("[dim #004400]──[/]")
        await self.add_message(content, "user")
        if content.startswith("/") or content.startswith("!"):
            await self._handle_command(content)
        else:
            await self._process_message(content)

    async def _handle_command(self, cmd_text):
        try:
            result = self._coder.commands.run(cmd_text)
            if isinstance(result, str):
                await self.add_message(result, "info")
        except SwitchCoder as sc:
            await self._switch_coder(sc)
        except Exception as e:
            await self.add_message(str(e), "error")
        finally:
            self._update_status()
            self.query_one("#message-input", Input).focus()

    async def _switch_coder(self, sc):
        kwargs = sc.kwargs
        kwargs["io"] = self._coder.io
        kwargs.setdefault("fnames", list(self._coder.abs_fnames))
        from .coders.base_coder import Coder
        self._coder = Coder.create(**kwargs)
        if self._git_repo:
            self._coder.repo = self._git_repo
            self._coder.root = self._git_repo.root
        self._all_commands = self._coder.commands.get_commands()
        mn = getattr(sc.kwargs.get("main_model"), "name", "UNKNOWN")
        ef = sc.kwargs.get("edit_format", "UNKNOWN")
        await self.add_message("Switched to " + mn.upper() + " / " + ef.upper(), "info")

    async def _process_message(self, content):
        if self._processing:
            await self.add_message("System busy — wait for current task", "warning")
            return
        self._processing = True
        self._update_status()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._run_coder_task, content)

    async def _after_coder_task(self):
        self._processing = False
        self._update_status()
        self.query_one("#message-input", Input).focus()

    def _run_coder_task(self, content):
        try:
            self._coder.run_one(content)
        except Exception as e:
            msg = str(e)
            if "clipboard" in msg.lower() or "image" in msg.lower():
                msg = "IMAGE INPUT UNSUPPORTED"
            asyncio.run_coroutine_threadsafe(
                self.add_message(msg, "error"), self._loop)
        finally:
            asyncio.run_coroutine_threadsafe(
                self._after_coder_task(), self._loop)

    # ── 快捷键 ──

    async def action_handle_ctrl_c(self):
        try:
            chat = self.query_one("#chat-panel", RichLog)
            if hasattr(chat, "selection") and chat.selection:
                return
            if hasattr(chat, "selected_text") and chat.selected_text:
                return
        except Exception:
            pass
        if self._processing:
            self._executor.shutdown(wait=False)
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="coder")
            self._processing = False
            self._update_status()
            await self.add_message("INTERRUPTED", "warning")
        else:
            await self.add_message("Press Ctrl+Q to quit", "info")

    async def action_copy_lines(self):
        text = None
        try:
            text = self.screen.get_selected_text()
        except Exception:
            text = None
        if not text:
            focused = self.focused
            if hasattr(focused, "selected_text"):
                try:
                    text = focused.selected_text
                except Exception:
                    text = None
        if not text and self._text_buffer:
            text = "\n".join(self._text_buffer)
        if text.strip():
            self.copy_to_clipboard(text)
            await self.add_message("Copied to clipboard", "info")

    async def action_quit(self):
        self._executor.shutdown(wait=False)
        await super().action_quit()

    async def action_clear_screen(self):
        self._ui_events.clear()
        self._text_buffer.clear()
        await self.add_message("Screen cleared", "info")

    async def action_focus_input(self):
        self.query_one("#message-input", Input).focus()
