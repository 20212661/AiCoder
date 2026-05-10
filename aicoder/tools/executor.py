"""Tool executor with mode-aware permissions, timeout, retry, and limits."""
from __future__ import annotations

import threading
import time

from ..permission_modes import (
    FILE_EDIT_TOOLS,
    ToolPermissionContext,
    can_use_tool_in_mode,
)
from .handlers.base import ToolHandler
from .result import ExecutionState, ToolCall, ToolResult

DEFAULT_TOOL_TIMEOUT = 60
MAX_TOOL_TIMEOUT = 600
MAX_WRITE_BYTES = 2 * 1024 * 1024
MAX_WRITE_LINES = 10000

MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 10.0
RETRYABLE_ERRORS = {
    "timeout",
    "subprocess.timeoutexpired",
    "connectionerror",
    "connectionreseterror",
    "brokenpipeerror",
    "oserror",
}


def _is_retryable_error(error_msg: str) -> bool:
    lower = error_msg.lower()
    return any(keyword in lower for keyword in RETRYABLE_ERRORS)


class ToolCoordinator:
    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        self._handlers[handler.name] = handler

    def get(self, tool_name: str) -> ToolHandler | None:
        return self._handlers.get(tool_name)


class _TimeoutWrapper:
    """Run a handler in a thread so timeouts work cross-platform."""

    def __init__(self, timeout: float):
        self.timeout = timeout
        self._timed_out = False

    def run(self, fn, *args, **kwargs):
        self._timed_out = False
        result_holder = [None]
        error_holder = [None]

        def target():
            try:
                result_holder[0] = fn(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - defensive guard
                error_holder[0] = exc

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
    def __init__(
        self,
        coordinator: ToolCoordinator,
        coder,
        state: ExecutionState | None = None,
    ):
        self._coordinator = coordinator
        self._coder = coder
        self._state = state or ExecutionState()

    @property
    def state(self) -> ExecutionState:
        return self._state

    def execute(self, tool_call: ToolCall, skip_permission: bool = False) -> ToolResult:
        if self._state.did_reject_tool:
            return ToolResult.fail(
                tool_call.name,
                "Skipped: previous tool was rejected",
            )

        handler = self._coordinator.get(tool_call.name)
        if not handler:
            self._state.on_failure(tool_call.name, tool_call.params)
            return ToolResult.fail(
                tool_call.name,
                "Unknown tool: " + tool_call.name,
            )

        if tool_call.name in FILE_EDIT_TOOLS:
            check = self._check_write_limits(tool_call)
            if check:
                return check

        error = handler.validate_params(tool_call)
        if error:
            self._state.on_failure(tool_call.name, tool_call.params)
            return ToolResult.fail(tool_call.name, "Invalid params: " + error)

        if not skip_permission:
            permission = self._get_permission_decision(tool_call, handler)
            if permission.behavior == "deny":
                self._state.on_failure(tool_call.name, tool_call.params)
                return ToolResult.blocked(tool_call.name, permission.reason)

            if permission.behavior == "ask" and handler.requires_approval:
                approved = self._request_approval(tool_call, handler, permission.reason)
                if not approved:
                    self._state.did_reject_tool = True
                    self._state.consecutive_mistake_count += 1
                    return ToolResult.create_rejected(tool_call.name)

            if permission.behavior == "allow" and permission.reason:
                self._emit_mode_reason(permission.reason)

        if self._state.is_looping:
            return ToolResult.fail(
                tool_call.name,
                "Loop detected: same tool called "
                + str(self._state.repeated_call_count)
                + " times",
            )

        return self._execute_with_retry(tool_call, handler)

    def _execute_with_retry(
        self,
        tool_call: ToolCall,
        handler: ToolHandler,
    ) -> ToolResult:
        timeout = self._resolve_timeout(tool_call, handler)
        structured_io = hasattr(self._coder.io, "tool_call_started") and hasattr(
            self._coder.io,
            "tool_call_finished",
        )

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

                last_result = ToolResult.fail(
                    tool_call.name,
                    f"Execution error: {err}",
                )
                if _is_retryable_error(str(err)):
                    continue
                break

            last_result = result
            if result.success or not _is_retryable_error(result.error or ""):
                break

        result = last_result

        if structured_io:
            present_result = self._format_result_for_ui(tool_call, result)
            self._coder.io.tool_call_finished(present_result, tool_call.params)
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
                self._coder.io.tool_error(
                    result.error[:200] if result.error else "Tool failed"
                )
            if result.success and tool_call.name in FILE_EDIT_TOOLS:
                self._state.had_file_edits = True

        return result

    def _format_result_for_ui(
        self,
        tool_call: ToolCall,
        result: ToolResult,
    ) -> ToolResult:
        if not self._state.is_plan_mode:
            return result

        text = result.output if result.success else (result.error or result.output)
        summary = self._summarize_plan_result(tool_call.name, text)
        if result.success:
            return ToolResult.ok(result.tool_name, summary, meta=result.meta)
        return ToolResult.fail(result.tool_name, summary, meta=result.meta)

    @staticmethod
    def _summarize_plan_result(tool_name: str, text: str) -> str:
        stripped = (text or "").strip()
        if not stripped:
            return "Completed."

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        first = lines[0] if lines else "Completed."

        if tool_name == "list_files":
            entry_count = (
                max(0, len(lines) - 1)
                if lines and lines[0].lower().startswith("contents of")
                else len(lines)
            )
            return f"Scanned directory contents ({entry_count} lines)."

        if tool_name == "read_file":
            for line in lines:
                if "|" in line:
                    return "Loaded file content for inspection."
            return "Read file."

        if tool_name == "search_files":
            return f"Search completed. {first[:120]}"

        if tool_name == "list_code_defs":
            return f"Extracted code definitions. {first[:120]}"

        if tool_name == "run_shell":
            return f"Ran shell command. {first[:120]}"

        return first[:160]

    def _resolve_timeout(self, tool_call: ToolCall, handler: ToolHandler) -> float:
        timeout_str = tool_call.get("timeout", "")
        if timeout_str:
            try:
                return min(float(timeout_str), MAX_TOOL_TIMEOUT)
            except ValueError:
                pass
        if hasattr(handler, "default_timeout"):
            return min(handler.default_timeout, MAX_TOOL_TIMEOUT)
        return DEFAULT_TOOL_TIMEOUT

    def _check_write_limits(self, tool_call: ToolCall) -> ToolResult | None:
        content = tool_call.get("content", "")
        if not content:
            return None

        content_bytes = len(content.encode("utf-8"))
        if content_bytes > MAX_WRITE_BYTES:
            return ToolResult.fail(
                tool_call.name,
                f"File too large: {content_bytes} bytes exceeds the {MAX_WRITE_BYTES} byte limit. "
                "Break the file into smaller writes or use edit_file for targeted changes.",
            )

        line_count = content.count("\n") + 1
        if line_count > MAX_WRITE_LINES:
            return ToolResult.fail(
                tool_call.name,
                f"File too large: {line_count} lines exceeds the {MAX_WRITE_LINES} line limit. "
                "Break the file into smaller writes or use edit_file for targeted changes.",
            )
        return None

    def execute_all(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        results = []
        for call in tool_calls:
            result = self.execute(call)
            results.append(result)
            self._coder.cur_messages.append(result.to_message())
            if self._state.did_reject_tool:
                self._coder.io.tool_warning("REJECTED - skipping remaining tools")
                break
            if self._state.too_many_errors:
                self._coder.io.tool_warning("ERROR LIMIT - stopping")
                break
        return results

    def _get_permission_decision(self, tool_call: ToolCall, handler: ToolHandler):
        coder = self._coder
        approval = getattr(coder, "_approval", None)
        mode_result = can_use_tool_in_mode(
            tool_call.name,
            tool_call.params,
            ToolPermissionContext(mode=self._state.mode),
            approval,
        )
        if mode_result.behavior != "ask":
            return mode_result

        if not handler.requires_approval:
            return mode_result

        if approval is not None:
            ok, reason = approval.should_auto_approve(tool_call.name, tool_call.params)
            if ok:
                return type(mode_result)(behavior="allow", reason=reason)
            if reason:
                return type(mode_result)(behavior="ask", reason=reason)

        if self._state.should_require_approval:
            return type(mode_result)(
                behavior="ask",
                reason="recent tool failures increased approval strictness",
            )

        return mode_result

    def _request_approval(self, tool_call, handler, reason_override=""):
        desc = (
            handler.description(tool_call)
            if hasattr(handler, "description")
            else tool_call.name
        )
        params_preview = str(tool_call.params)[:200]
        coder = self._coder
        reason = reason_override or ""
        if hasattr(coder, "_approval") and coder._approval is not None:
            _, auto_reason = coder._approval.should_auto_approve(
                tool_call.name,
                tool_call.params,
            )
            if auto_reason:
                reason = auto_reason

        if hasattr(coder, "_approval") and coder._approval is not None:
            desc = coder._approval.format_approval_title(tool_call.name, desc)

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
        return self._coder.io.confirm_ask(
            "Allow tool call?\n  " + full_desc + "\n  " + params_preview
        )

    def _emit_mode_reason(self, reason: str) -> None:
        if hasattr(self._coder.io, "tool_output"):
            self._coder.io.tool_output(f"  [mode] {reason}")

    def reset_state(self):
        self._state.reset()

    def set_mode(self, mode: str):
        self._state.mode = mode
