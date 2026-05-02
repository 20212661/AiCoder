"""Tool executor with plan/act mode, timeout, retry, and resource limits"""
import threading
import time
from functools import wraps
from .result import ToolCall, ToolResult, ExecutionState
from .handlers.base import ToolHandler

PLAN_MODE_BLOCKED_TOOLS = {"edit_file", "write_file"}
FILE_EDIT_TOOLS = {"edit_file", "write_file"}

# ── 执行策略常量 ──
DEFAULT_TOOL_TIMEOUT = 60       # 普通工具超时 60s
MAX_TOOL_TIMEOUT = 600          # 工具最大超时 600s
MAX_WRITE_BYTES = 2 * 1024 * 1024  # 写文件上限 2MB
MAX_WRITE_LINES = 10000         # 写文件行数上限

# ── 重试策略 ──
MAX_RETRIES = 2                 # 最大重试次数（不含首次）
RETRY_BASE_DELAY = 1.0          # 指数退避基础延迟（秒）
RETRY_MAX_DELAY = 10.0          # 最大退避延迟（秒）
RETRYABLE_ERRORS = {
    "timeout", "subprocess.TimeoutExpired", "ConnectionError",
    "ConnectionResetError", "BrokenPipeError", "OSError",
}


def _is_retryable_error(error_msg: str) -> bool:
    """判断错误是否值得重试"""
    lower = error_msg.lower()
    return any(kw in lower for kw in RETRYABLE_ERRORS)


class ToolCoordinator:
    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        self._handlers[handler.name] = handler

    def get(self, tool_name: str) -> ToolHandler | None:
        return self._handlers.get(tool_name)


class _TimeoutWrapper:
    """为任意可调用对象添加超时强制终止能力。

    使用 threading 实现跨平台兼容（signal.alarm 仅限 Unix）。
    """

    def __init__(self, timeout: float):
        self.timeout = timeout
        self._timer: threading.Timer | None = None
        self._timed_out = False

    def run(self, fn, *args, **kwargs):
        self._timed_out = False
        result_holder = [None]
        error_holder = [None]

        def target():
            try:
                result_holder[0] = fn(*args, **kwargs)
            except Exception as e:
                error_holder[0] = e

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout)

        if thread.is_alive():
            self._timed_out = True
            return None, TimeoutError(
                f"Tool execution timed out after {self.timeout:.0f}s"
            )

        if error_holder[0] is not None:
            return None, error_holder[0]

        return result_holder[0], None

    @property
    def did_timeout(self) -> bool:
        return self._timed_out


class ToolExecutor:
    def __init__(self, coordinator: ToolCoordinator, coder, state: ExecutionState | None = None):
        self._coordinator = coordinator
        self._coder = coder
        self._state = state or ExecutionState()

    @property
    def state(self) -> ExecutionState:
        return self._state

    def execute(self, tool_call: ToolCall) -> ToolResult:
        if self._state.did_reject_tool:
            return ToolResult.fail(tool_call.name, "Skipped: previous tool was rejected")

        handler = self._coordinator.get(tool_call.name)
        if not handler:
            self._state.on_failure(tool_call.name, tool_call.params)
            return ToolResult.fail(tool_call.name, "Unknown tool: " + tool_call.name)

        # 计划模式：拦截写操作工具
        if self._state.is_plan_mode and tool_call.name in PLAN_MODE_BLOCKED_TOOLS:
            return ToolResult.blocked(
                tool_call.name,
                "BLOCKED in PLAN MODE. You are in plan/read-only mode. "
                "Use read_file, search_files, list_files, or list_code_defs to explore. "
                "When ready, the user will switch to ACT MODE for file editing."
            )

        # 资源预检：写操作大小限制
        if tool_call.name in FILE_EDIT_TOOLS:
            check = self._check_write_limits(tool_call)
            if check:
                return check

        error = handler.validate_params(tool_call)
        if error:
            self._state.on_failure(tool_call.name, tool_call.params)
            return ToolResult.fail(tool_call.name, "Invalid params: " + error)

        if handler.requires_approval and not self._can_auto_approve(tool_call, handler):
            approved = self._request_approval(tool_call, handler)
            if not approved:
                self._state.did_reject_tool = True
                self._state.consecutive_mistake_count += 1
                return ToolResult.create_rejected(tool_call.name)

        if self._state.is_looping:
            return ToolResult.fail(tool_call.name,
                "Loop detected: same tool called " + str(self._state.repeated_call_count) + " times")

        # ── 带超时和重试的执行 ──
        result = self._execute_with_retry(tool_call, handler)
        return result

    def _execute_with_retry(self, tool_call: ToolCall, handler: ToolHandler) -> ToolResult:
        """带超时和指数退避重试的工具执行"""
        timeout = self._resolve_timeout(tool_call, handler)
        structured_io = hasattr(self._coder.io, "tool_call_started") and hasattr(self._coder.io, "tool_call_finished")

        if structured_io:
            self._coder.io.tool_call_started(tool_call.name, tool_call.params)
        else:
            self._coder.io.tool_output("Executing: " + tool_call.name)

        last_result = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
                if hasattr(self._coder.io, "tool_output"):
                    self._coder.io.tool_output(
                        f"  Retrying {tool_call.name} (attempt {attempt + 1}/{MAX_RETRIES + 1}, "
                        f"waiting {delay:.1f}s)..."
                    )
                time.sleep(delay)

            # 带超时包装执行
            wrapper = _TimeoutWrapper(timeout)
            result, err = wrapper.run(handler.execute, tool_call, self._coder)

            if err is not None:
                if isinstance(err, TimeoutError) or wrapper.did_timeout:
                    msg = (
                        f"Tool timed out after {timeout:.0f}s. "
                        "Try breaking the operation into smaller steps."
                    )
                    last_result = ToolResult.fail(tool_call.name, msg)
                    if _is_retryable_error(msg):
                        continue
                    break
                last_result = ToolResult.fail(tool_call.name, f"Execution error: {err}")
                if _is_retryable_error(str(err)):
                    continue
                break

            last_result = result
            # 成功或非重试错误 → 退出循环
            if result.success or not _is_retryable_error(result.error or ""):
                break
            # 可重试失败 → 继续

        result = last_result

        if structured_io:
            self._coder.io.tool_call_finished(result, tool_call.params)
            if result.success:
                self._state.on_success(tool_call.name, tool_call.params)
                if tool_call.name in FILE_EDIT_TOOLS:
                    self._state.had_file_edits = True
            else:
                self._state.on_failure(tool_call.name, tool_call.params)
        else:
            if result.success:
                self._state.on_success(tool_call.name, tool_call.params)
                output = result.output.strip()
                if output:
                    preview = output[:500] + ("..." if len(output) > 500 else "")
                    for line in preview.splitlines():
                        self._coder.io.tool_output("  " + line)
            else:
                self._state.on_failure(tool_call.name, tool_call.params)
                self._coder.io.tool_error(result.error[:200] if result.error else "Tool failed")
            if result.success and tool_call.name in FILE_EDIT_TOOLS:
                self._state.had_file_edits = True

        return result

    def _resolve_timeout(self, tool_call: ToolCall, handler: ToolHandler) -> float:
        """解析工具超时时间：优先 tool_call 参数 > handler 属性 > 默认值"""
        timeout_str = tool_call.get("timeout", "")
        if timeout_str:
            try:
                t = float(timeout_str)
                return min(t, MAX_TOOL_TIMEOUT)
            except ValueError:
                pass
        if hasattr(handler, "default_timeout"):
            return min(handler.default_timeout, MAX_TOOL_TIMEOUT)
        return DEFAULT_TOOL_TIMEOUT

    def _check_write_limits(self, tool_call: ToolCall) -> ToolResult | None:
        """写操作资源预检：文件大小、行数"""
        content = tool_call.get("content", "")
        if not content:
            return None

        content_bytes = len(content.encode("utf-8"))
        if content_bytes > MAX_WRITE_BYTES:
            return ToolResult.fail(
                tool_call.name,
                f"File too large: {content_bytes} bytes exceeds the {MAX_WRITE_BYTES} byte limit. "
                "Break the file into smaller writes or use edit_file for targeted changes."
            )

        line_count = content.count("\n") + 1
        if line_count > MAX_WRITE_LINES:
            return ToolResult.fail(
                tool_call.name,
                f"File too large: {line_count} lines exceeds the {MAX_WRITE_LINES} line limit. "
                "Break the file into smaller writes or use edit_file for targeted changes."
            )
        return None

    def execute_all(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        results = []
        for call in tool_calls:
            result = self.execute(call)
            results.append(result)
            self._coder.cur_messages.append(result.to_message())
            if self._state.did_reject_tool:
                self._coder.io.tool_warning("REJECTED — skipping remaining tools")
                break
            if self._state.too_many_errors:
                self._coder.io.tool_warning("ERROR LIMIT — stopping")
                break
        return results

    def _can_auto_approve(self, tool_call, handler):
        if not handler.requires_approval:
            return True
        coder = self._coder
        if hasattr(coder, "_approval") and coder._approval is not None:
            ok, reason = coder._approval.should_auto_approve(
                tool_call.name, tool_call.params
            )
            if ok:
                if hasattr(coder.io, "tool_output"):
                    coder.io.tool_output(f"  [auto] {reason}")
                return True
        if self._state.should_require_approval:
            return False
        return False

    def _request_approval(self, tool_call, handler):
        desc = handler.description(tool_call) if hasattr(handler, "description") else tool_call.name
        params_preview = str(tool_call.params)[:200]
        coder = self._coder
        reason = ""
        if hasattr(coder, "_approval") and coder._approval is not None:
            _, reason = coder._approval.should_auto_approve(tool_call.name, tool_call.params)
        full_desc = desc
        if reason:
            full_desc = f"{desc}\n  Reason: {reason}"
        if hasattr(self._coder.io, "request_structured_approval"):
            approval_kind = "command" if tool_call.name == "run_shell" else "tool"
            return self._coder.io.request_structured_approval(
                approval_kind,
                full_desc,
                params_preview,
            )
        return self._coder.io.confirm_ask("Allow tool call?\n  " + full_desc + "\n  " + params_preview)

    def reset_state(self):
        self._state.reset()

    def set_mode(self, mode: str):
        self._state.mode = mode
