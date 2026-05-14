# LangChain Runtime Tools Contract

> Defines the safety boundary and naming constraints for aiCoder's LangChain tools.

## Safety Boundary

1. LangChain Tools only adapt schema and invocation — they never directly execute file, Shell, or Git operations.
2. All real execution must go through `coder.tool_executor.execute(ToolCall(...))`.
3. Tool failures are converted to `ToolMessage` via `handle_tool_errors` middleware, never allowed to bubble as unhandled exceptions.
4. User rejection, safety blocks, and permission denials must be preserved as semantic error messages the model can reason about.

## Reserved Parameter Names

The following names are reserved by LangChain and must **not** appear as model-visible tool arguments:

| Reserved Name | Owner | Reason |
|---------------|-------|--------|
| `config` | `RunnableConfig` | Injected by LangChain runtime, not model-visible |
| `runtime` | `ToolRuntime` | Provides state/store/stream_writer access |

Current tool schemas are confirmed clean — no parameter uses `config` or `runtime`.

## Error Handling

- `handle_tool_errors` middleware wraps all tool calls via `wrap_tool_call`.
- On exception, returns `ToolMessage` with structured error message using `format_tool_error_message()`.
- Error categories preserved in message:
  - **User rejected** — tool call was rejected by user approval
  - **Safety/policy blocked** — permission denied or policy violation
  - **Execution failed** — general tool execution error
- The model receives actionable guidance: "Check arguments, respect safety policy, or choose a safer alternative."

## What Is NOT In Scope

- `ToolRuntime` state/store/stream_writer — not used in current phase.
- Server-side tools — not used.
- `Command` for LangGraph state updates — not used.
- `ToolRuntime` for passing session_id/thread_id/tool_call_id — future phase.

## Future Considerations

- `ToolRuntime` may be used to pass `session_id`, `thread_id`, `tool_call_id` in later phases.
- Structured output schema (`AICoderResponse`) is separate from tool schemas and does not interact with reserved names.
