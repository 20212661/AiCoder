"""Tool executor with plan/act mode support"""
from .result import ToolCall, ToolResult, ExecutionState
from .handlers.base import ToolHandler

PLAN_MODE_BLOCKED_TOOLS = {"edit_file", "write_file"}

class ToolCoordinator:
    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        self._handlers[handler.name] = handler

    def get(self, tool_name: str) -> ToolHandler | None:
        return self._handlers.get(tool_name)


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
        structured_io = hasattr(self._coder.io, "tool_call_started") and hasattr(self._coder.io, "tool_call_finished")
        if structured_io:
            self._coder.io.tool_call_started(tool_call.name, tool_call.params)
        else:
            self._coder.io.tool_output("Executing: " + tool_call.name)
        result = handler.execute(tool_call, self._coder)

        if structured_io:
            self._coder.io.tool_call_finished(result, tool_call.params)
        elif result.success:
            self._state.on_success(tool_call.name, tool_call.params)
            # Show tool result output to user (truncated for readability)
            output = result.output.strip()
            if output:
                preview = output[:500] + ("..." if len(output) > 500 else "")
                for line in preview.splitlines():
                    self._coder.io.tool_output("  " + line)
        else:
            self._state.on_failure(tool_call.name, tool_call.params)
            self._coder.io.tool_error(result.error[:200] if result.error else "Tool failed")
        if structured_io:
            if result.success:
                self._state.on_success(tool_call.name, tool_call.params)
            else:
                self._state.on_failure(tool_call.name, tool_call.params)
        return result

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
        if self._state.should_require_approval:
            return False
        return False

    def _request_approval(self, tool_call, handler):
        desc = handler.description(tool_call) if hasattr(handler, "description") else tool_call.name
        params_preview = str(tool_call.params)[:200]
        return self._coder.io.confirm_ask("Allow tool call?\n  " + desc + "\n  " + params_preview)

    def reset_state(self):
        self._state.reset()

    def set_mode(self, mode: str):
        self._state.mode = mode
