"""工具调用、结果与执行状态数据类"""
import difflib
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    params: dict[str, str] = field(default_factory=dict)
    def get(self, key: str, default: str = "") -> str:
        return self.params.get(key, default)


@dataclass
class TextBlock:
    content: str


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: str = ""
    error: str = ""
    rejected: bool = False
    meta: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, tool_name: str, output: str, meta: dict | None = None) -> "ToolResult":
        return cls(tool_name=tool_name, success=True, output=output, meta=dict(meta or {}))

    @classmethod
    def fail(cls, tool_name: str, error: str, meta: dict | None = None) -> "ToolResult":
        return cls(tool_name=tool_name, success=False, error=error, output=error, meta=dict(meta or {}))

    @classmethod
    def create_rejected(cls, tool_name: str) -> "ToolResult":
        return cls(tool_name=tool_name, success=False, rejected=True, error="User rejected the tool call.")

    @classmethod
    def blocked(cls, tool_name: str, reason: str) -> "ToolResult":
        return cls(tool_name=tool_name, success=False, error=reason)

    def to_message(self) -> dict:
        label = "[" + self.tool_name + "]"
        if self.rejected:
            return {"role": "user", "content": label + " REJECTED by user."}
        if self.success:
            if self.output.strip():
                t = label + " Result:\n" + self.output
            else:
                t = label + " OK (no output)."
            return {"role": "user", "content": t}
        return {"role": "user", "content": label + " FAILED:\n" + self.error}


def build_unified_diff(old_text: str, new_text: str, path: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=path,
            tofile=path,
            lineterm="",
        )
    )


@dataclass
class ExecutionState:
    consecutive_mistake_count: int = 0
    last_tool_name: str = ""
    last_tool_params: dict = field(default_factory=dict)
    repeated_call_count: int = 0
    did_reject_tool: bool = False
    had_file_edits: bool = False
    max_repeated_calls: int = 3
    max_consecutive_mistakes: int = 5
    mode: str = "act"

    def reset(self):
        self.consecutive_mistake_count = 0
        self.last_tool_name = ""
        self.last_tool_params = {}
        self.repeated_call_count = 0
        self.did_reject_tool = False
        self.had_file_edits = False

    def on_success(self, tool_name: str, params: dict):
        self.consecutive_mistake_count = 0
        self._update_last(tool_name, params)

    def on_failure(self, tool_name: str, params: dict):
        self.consecutive_mistake_count += 1
        self._update_last(tool_name, params)

    def _update_last(self, tool_name: str, params: dict):
        if tool_name == self.last_tool_name and params == self.last_tool_params:
            self.repeated_call_count += 1
        else:
            self.repeated_call_count = 0
        self.last_tool_name = tool_name
        self.last_tool_params = dict(params)

    @property
    def is_looping(self) -> bool:
        return self.repeated_call_count >= self.max_repeated_calls

    @property
    def too_many_errors(self) -> bool:
        return self.consecutive_mistake_count >= self.max_consecutive_mistakes

    @property
    def should_require_approval(self) -> bool:
        return self.consecutive_mistake_count >= 3

    @property
    def is_plan_mode(self) -> bool:
        return self.mode in ("plan", "sniff")
