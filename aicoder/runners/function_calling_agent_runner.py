"""Function Calling agent runner — native structured tool_calls protocol.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §6.4
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import litellm

from aicoder.exceptions import LLMError
from aicoder.parsers.function_call_parser import FunctionCallParser
from aicoder.runners.base_agent_runner import BaseAgentRunner, StepResult
from aicoder.tool_schema_builder import ToolSchemaBuilder
from aicoder.tools.result import ToolCall, ToolResult

if TYPE_CHECKING:
    from aicoder.agent_step_store import AgentStepStore
    from aicoder.coders.base_coder import Coder
    from aicoder.tools.registry import ToolRegistry


class FunctionCallingAgentRunner(BaseAgentRunner):
    """Runner using native function calling (OpenAI-compatible tool_calls)."""

    def __init__(
        self,
        coder: "Coder",
        session_id: str,
        mode: str,
        tool_registry: "ToolRegistry",
        step_store: "AgentStepStore",
    ) -> None:
        super().__init__(coder, session_id, mode, tool_registry, step_store)
        self._parser = FunctionCallParser()

    def run_step(
        self,
        messages: list[dict],
        iteration: int,
        max_iterations: int,
    ) -> StepResult:
        step = self._create_step(iteration)

        # Build tools schema
        tools = ToolSchemaBuilder.build_prompt_message_tools(self.tool_registry, self.mode)

        # Disable tools on last iteration (§14.3)
        if self._should_disable_tools(iteration, max_iterations):
            tools = None

        # Call LLM with tools
        content, raw_tool_calls = self._call_llm_with_tools(messages, tools)

        # Parse response
        parser_events = self._parser.parse_response(content, raw_tool_calls)

        # Extract actions
        tool_calls: list[ToolCall] = []
        tool_call_ids: list[str] = []
        failed_observations: list[ToolResult] = []
        thought = ""
        is_final = False

        # Build a name -> id mapping from raw LLM tool_calls
        raw_id_map: dict[str, str] = {}
        if raw_tool_calls:
            for idx, raw_tc in enumerate(raw_tool_calls):
                name = raw_tc.get("function", {}).get("name", f"unknown_{idx}")
                tc_id = raw_tc.get("id") or f"{step.id}_{idx}"
                raw_id_map[name] = tc_id

        for evt in parser_events:
            if evt.kind == "action" and evt.action_name:
                if isinstance(evt.action_input, dict):
                    params = evt.action_input
                    tool_calls.append(ToolCall(name=evt.action_name, params=params))
                    tc_id = raw_id_map.get(evt.action_name, f"{step.id}_{len(tool_calls) - 1}")
                    tool_call_ids.append(tc_id)
                else:
                    params, norm_error = self._normalize_tool_params(
                        evt.action_input, evt.action_name,
                    )
                    if norm_error:
                        failed_observations.append(
                            ToolResult.fail(evt.action_name, norm_error),
                        )
                    else:
                        tool_calls.append(ToolCall(name=evt.action_name, params=params))
                        tc_id = raw_id_map.get(evt.action_name, f"{step.id}_{len(tool_calls) - 1}")
                        tool_call_ids.append(tc_id)
            elif evt.kind == "text":
                thought = evt.text
            elif evt.kind == "final":
                is_final = True

        clean_text = content or ""

        if tool_calls:
            first = tool_calls[0]
            self._update_step_after_parse(
                step,
                thought=thought,
                action_name=first.name,
                action_input=dict(first.params),
                action_raw=json.dumps(raw_tool_calls) if raw_tool_calls else "",
            )
            # v1.2: emit additional tool_call events for multi-tool-call scenarios
            for extra_tc in tool_calls[1:]:
                self.step_store.event_store.append(
                    iteration=step.iteration,
                    kind="tool_call",
                    payload={
                        "step_id": step.id,
                        "tool_name": extra_tc.name,
                        "tool_input": dict(extra_tc.params),
                    },
                )
        else:
            final_answer = clean_text.strip()
            self._update_step_after_parse(step, thought=thought)
            self._finalize_step(step, final_answer=final_answer)

        return StepResult(
            thought=thought,
            tool_calls=tool_calls,
            tool_call_ids=tool_call_ids,
            failed_observations=failed_observations,
            final_answer=clean_text if (is_final or not tool_calls) else "",
            clean_text=clean_text,
            raw_response=content or "",
            step=step,
        )

    def _call_llm_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> tuple[str | None, list[dict] | None]:
        """Call LLM with optional tools. Returns (content, tool_calls)."""
        io = self.coder.io

        for attempt in range(3):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model.backend_model,
                    "messages": messages,
                    "stream": False,
                    "max_tokens": self.model.max_output_tokens,
                    "timeout": 60,
                }
                if tools:
                    kwargs["tools"] = tools

                response = litellm.completion(**kwargs)
                message = response.choices[0].message
                content = message.content or ""
                raw_tool_calls = None

                if hasattr(message, "tool_calls") and message.tool_calls:
                    raw_tool_calls = [
                        {
                            "id": tc.id,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ]

                # Stream text to IO if present
                if content:
                    if self.coder.stream:
                        io.print_streaming(content)
                    else:
                        io.print_assistant_output(content)

                return content, raw_tool_calls

            except Exception as err:
                if attempt < 2:
                    delay = 2 ** attempt
                    io.tool_warning(
                        f"LLM error [{self.model.name}] "
                        f"(retry {attempt + 1}/3 in {delay}s): {err}"
                    )
                    time.sleep(delay)
                else:
                    raise LLMError(self.model.name, str(err))

        return "", None

    def _normalize_tool_params(
        self,
        action_input: Any,
        tool_name: str,
    ) -> tuple[dict | None, str | None]:
        """Normalize tool arguments to a dict.

        Rules:
        1. Already dict → use as-is
        2. str + single required param → auto-wrap {param_name: str}
        3. str → try json.loads; if dict, use it
        4. Other types → attempt safe conversion
        5. Fail → return (None, error_message)
        """
        if isinstance(action_input, dict):
            return action_input, None

        if isinstance(action_input, str):
            spec = self.tool_registry.get(tool_name)
            if spec:
                required = spec.required_params()
                if len(required) == 1:
                    return {required[0].name: action_input}, None

            try:
                parsed = json.loads(action_input)
                if isinstance(parsed, dict):
                    return parsed, None
            except (json.JSONDecodeError, ValueError):
                pass

            return None, "Invalid params: tool arguments could not be normalized to a dict"

        # Non-dict, non-str: attempt conversion
        try:
            converted = dict(action_input)
            if isinstance(converted, dict):
                return converted, None
        except (TypeError, ValueError):
            pass

        return None, "Invalid params: tool arguments could not be normalized to a dict"
