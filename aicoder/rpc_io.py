"""
JSON-RPC over stdio 的 IO 实现
供外部 TUI（如 aicoder-tui）通过子进程 stdio 通信
"""
import json
import os
import sys
import uuid
import threading
from queue import Queue, Empty

from .io import InputOutput


def _ensure_utf8(stream):
    """Wrap a text stream to guarantee UTF-8 encoding (fixes Windows GBK default)."""
    if stream.encoding and stream.encoding.lower().replace("-", "") == "utf8":
        return stream
    import io
    return io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace", line_buffering=True)


class JsonRpcIO(InputOutput):
    """通过 JSON-RPC stdio 与 TypeScript TUI 通信的 IO 实现"""

    def __init__(self):
        super().__init__(pretty=False, yes=False)
        self.reader = _ensure_utf8(sys.stdin)
        self.writer = _ensure_utf8(sys.stdout)
        self._lock = threading.Lock()
        self._pending_responses: dict[str, Queue] = {}
        self._input_queue: Queue = Queue()  # 持久化输入队列，防止消息丢失
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._current_model_name = "unknown"

    def start(self):
        """启动后台 reader 线程"""
        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True
        )
        self._reader_thread.start()

    def stop(self):
        """停止 reader 线程"""
        self._running = False
        # Unblock the background stdin reader so --serve can exit cleanly
        # on /quit and during test teardown.
        # On Windows, closing the TextIOWrapper or its buffer does NOT
        # interrupt a blocking readline() at the C level.  We must close
        # the underlying OS file descriptor directly.
        try:
            raw = getattr(self.reader, "buffer", self.reader)
            fd = raw.fileno()
            os.close(fd)
        except Exception:
            pass
        try:
            self.reader.close()
        except Exception:
            pass
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

    def _read_loop(self):
        """后台线程：从 stdin 逐行读取 JSON-RPC 消息"""
        try:
          for line in self.reader:
            if not self._running:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self._notify("parse_error", {"raw": line})
                continue

            msg_id = msg.get("id")
            method = msg.get("method")

            # 响应：匹配 pending request
            if msg_id and msg_id in self._pending_responses:
                q = self._pending_responses.pop(msg_id)
                q.put(msg.get("result"))
                continue

            # 请求：TUI 发来的方法调用
            if method:
                self._handle_request(method, msg.get("params", {}), msg_id)
        except Exception as e:
            sys.stderr.write(f"[rpc] read_loop CRASHED: {e}\n"); sys.stderr.flush()

    def _handle_request(self, method: str, params: dict, msg_id: str | None):
        """处理来自 TUI 的请求"""
        if method == "input/submit":
            text = params.get("text", "")
            self._input_queue.put(text)  # 始终入队，不丢失
            if msg_id:
                self._send_response(msg_id, {"status": "ok"})
            return

        if method == "cancel/generation":
            self._notify("generation_cancelled", {})
            if msg_id:
                self._send_response(msg_id, {"status": "ok"})
            return

        if method == "approval/respond":
            approval_id = params.get("id", "")
            approved = params.get("approved", False)
            q = self._pending_responses.get(approval_id)
            if q:
                q.put(approved)
            if msg_id:
                self._send_response(msg_id, {"status": "ok"})
            return

        if method == "confirm/respond":
            confirm_id = params.get("id", "")
            confirmed = params.get("confirmed", False)
            q = self._pending_responses.get(confirm_id)
            if q:
                q.put(confirmed)
            if msg_id:
                self._send_response(msg_id, {"status": "ok"})
            return

        if method == "session/list":
            from .session import list_sessions
            sessions = list_sessions()
            if msg_id:
                self._send_response(msg_id, sessions)
            return

        if method == "session/new":
            self._input_queue.put("/clear")
            if msg_id:
                self._send_response(msg_id, {"status": "ok"})
            return

        if method == "session/resume":
            session_id = params.get("id", "")
            self._input_queue.put(f"/resume {session_id}")
            if msg_id:
                self._send_response(msg_id, {"status": "ok"})
            return

        if method == "model/list":
            from .models import list_model_names

            if msg_id:
                self._send_response(msg_id, {
                    "models": list_model_names(),
                    "currentModel": self._current_model_name,
                })
            return

        if method == "model/switch":
            model_name = params.get("model", "")
            if model_name:
                self._input_queue.put(f"/model {model_name}")
            if msg_id:
                self._send_response(msg_id, {"status": "ok"})
            return

        if msg_id:
            self._send_response(msg_id, None, error={
                "code": -32601,
                "message": f"Unknown method: {method}",
            })

    def _notify(self, method: str, params: dict | None = None):
        """发送 JSON-RPC notification（无需响应）"""
        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        })
        with self._lock:
            self.writer.write(msg + "\n")
            self.writer.flush()

    def _send_response(self, msg_id: str, result, error=None):
        """发送 JSON-RPC response"""
        msg = {"jsonrpc": "2.0", "id": msg_id}
        if error:
            msg["error"] = error
        else:
            msg["result"] = result
        with self._lock:
            self.writer.write(json.dumps(msg) + "\n")
            self.writer.flush()

    def _wait_response(self, request_key: str, timeout: float = 300):
        """阻塞等待 TUI 回复"""
        q = Queue()
        self._pending_responses[request_key] = q
        try:
            return q.get(timeout=timeout)
        except Empty:
            return None
        finally:
            self._pending_responses.pop(request_key, None)

    # ── InputOutput 接口实现 ──

    def get_input(self, root, inchat_files, addable_files, commands,
                  read_only_fnames, edit_format=""):
        """等待 TUI 发送用户输入（支持排队）"""
        self._notify("input/request", {
            "root": root,
            "inchat_files": list(inchat_files) if inchat_files else [],
            "addable_files": list(addable_files) if addable_files else [],
            "commands": list(commands) if commands else [],
        })
        # RPC/TUI mode should keep the backend process alive while idle.
        # Use a blocking wait here instead of a finite timeout so the TUI
        # does not get disconnected after several minutes of inactivity.
        return self._input_queue.get()

    def tool_output(self, message="", bold=False):
        self._notify("tool/output", {"message": message, "bold": bold})

    def tool_error(self, message=""):
        self._notify("tool/error", {"message": message})

    def tool_warning(self, message=""):
        self._notify("tool/warning", {"message": message})

    def user_input(self, message, log_only=True):
        if not log_only:
            self._notify("user_input", {"message": message})

    def confirm_ask(self, question, default="y"):
        approval_id = str(uuid.uuid4())
        self._notify("confirm/ask", {
            "id": approval_id,
            "question": question,
            "default": default,
        })
        result = self._wait_response(approval_id)
        if result is None:
            return default == "y"
        return bool(result)

    def approval_request(self, question, diff=None):
        """审批请求（用于文件编辑等操作）"""
        approval_id = str(uuid.uuid4())
        self._notify("approval/request", {
            "id": approval_id,
            "question": question,
            "diff": diff,
        })
        result = self._wait_response(approval_id)
        return bool(result)

    def request_structured_approval(self, kind, description, preview=""):
        """Tool executor 调用的审批接口 — 走 approval_request 通道"""
        return self.approval_request(description, diff=preview)

    def print_assistant_output(self, text):
        self._notify("assistant/output", {"text": text})

    def print_streaming(self, chunk):
        self._notify("stream/token", {"text": chunk})

    def finalize_streaming(self, full_text, is_intermediate=False):
        self._notify("stream/finalize", {"text": full_text, "is_intermediate": is_intermediate})

    def tool_call_started(self, tool_name: str, params: dict):
        """通知 TUI 工具调用开始（结构化 IO）"""
        self._notify("tool/call_started", {"tool": tool_name, "args": params})

    def tool_call_finished(self, result, params: dict | None = None):
        """通知 TUI 工具调用结束（结构化 IO）"""
        from .tools.result import ToolResult
        if isinstance(result, ToolResult):
            self._notify("tool/call_finished", {
                "tool": result.tool_name,
                "result": result.output or result.error or "",
                "success": result.success,
            })
        else:
            self._notify("tool/call_finished", {
                "tool": "",
                "result": str(result),
                "success": True,
            })

    def _build_status(self, coder, phase="idle") -> dict:
        """构建统一的状态广播 payload（model / mode / planMode / yolo / phase）"""
        return {
            "model": coder.main_model.name if coder.main_model else "unknown",
            "planMode": bool(getattr(coder.tool_executor.state, "is_plan_mode", False)),
            "mode": getattr(coder.tool_executor.state, "mode", "act"),
            "yolo": bool(getattr(coder, "_approval", None) and coder._approval.settings.yolo),
            "phase": phase,
        }

    def serve(self, coder):
        """进入 RPC 服务主循环"""
        self.start()
        self._current_model_name = coder.main_model.name if coder.main_model else "unknown"
        self._notify("ready", self._build_status(coder))

        try:
            from .commands import SwitchCoder
            from .coders.base_coder import Coder

            while self._running:
                try:
                    commands = coder.commands.get_commands() if coder.commands else []
                    user_input = self.get_input(
                        coder.root,
                        coder.get_inchat_relative_files(),
                        coder.get_addable_relative_files(),
                        commands,
                        [],
                    )
                    if user_input is None:
                        break

                    # 处理斜杠命令
                    if user_input.startswith("/"):
                        if user_input.strip() == "/quit":
                            break
                        if user_input.strip() == "/clear":
                            coder.done_messages = []
                            coder.cur_messages = []
                            continue
                        # 交给命令系统分发（如 /plan, /act, /model 等）
                        if coder.commands and coder.commands.is_command(user_input):
                            # 创建 assistant message 容器，让 tool_output 有地方附着
                            self._notify("stream/token", {"text": ""})
                            try:
                                cmd_result = coder.commands.run(user_input)
                            except SwitchCoder as e:
                                cmd_result = e
                            finally:
                                self._notify("stream/finalize", {"text": ""})
                            if isinstance(cmd_result, SwitchCoder):
                                kwargs = cmd_result.kwargs
                                kwargs["io"] = self
                                kwargs.setdefault("fnames", list(coder.abs_fnames))
                                coder = Coder.create(**kwargs)
                                self._current_model_name = coder.main_model.name if coder.main_model else "unknown"
                            self._notify("status/update", self._build_status(coder))
                            continue

                    thinking_phase = "sniffing" if getattr(getattr(coder, "tool_exec_state", None), "mode", "act") == "sniff" else ("planning" if getattr(getattr(coder, "tool_exec_state", None), "is_plan_mode", False) else "acting")
                    self._notify("status/update", self._build_status(coder, thinking_phase))
                    result = coder.run(with_message=user_input)
                    if isinstance(result, SwitchCoder):
                        kwargs = result.kwargs
                        kwargs["io"] = self
                        kwargs.setdefault("fnames", list(coder.abs_fnames))
                        coder = Coder.create(**kwargs)
                        self._current_model_name = coder.main_model.name if coder.main_model else "unknown"
                    self._notify("status/update", self._build_status(coder, "idle"))

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    self._notify("error", {"message": str(e)})

        finally:
            self.stop()
            try:
                self._notify("shutdown", {})
            except Exception:
                pass
            # Close stdout to prevent the process from hanging during
            # Python's shutdown sequence when the parent stops reading.
            try:
                self.writer.close()
            except Exception:
                pass
