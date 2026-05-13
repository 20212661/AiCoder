"""CoT (Chain-of-Thought) agent runner — XML/JSON text tool-call protocol.

Design reference: docs/aicoder-agent-runner-refactor-design-v1.md §6.3
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from aicoder.exceptions import LLMError
from aicoder.parsers.cot_xml_tool_parser import CotXmlToolParser
from aicoder.parsers.base import ParserEvent
from aicoder.runners.base_agent_runner import BaseAgentRunner, StepResult
from aicoder.tools.result import TextBlock, ToolCall

if TYPE_CHECKING:
    from aicoder.agent_step_store import AgentStepStore
    from aicoder.coders.base_coder import Coder
    from aicoder.tools.registry import ToolRegistry


class CotAgentRunner(BaseAgentRunner):
    """CoT/ReAct style runner using text-based tool calling via XML or JSON."""

    def __init__(
        self,
        coder: "Coder",
        session_id: str,
        mode: str,
        tool_registry: "ToolRegistry",
        step_store: "AgentStepStore",
    ) -> None:
        super().__init__(coder, session_id, mode, tool_registry, step_store)
        self._parser = CotXmlToolParser()

    def run_step(
        self,
        messages: list[dict],
        iteration: int,
        max_iterations: int,
    ) -> StepResult:
        step = self._create_step(iteration)

        # Call LLM (same logic as graph/nodes._call_llm)
        response_text = self._call_llm(messages)

        # Parse output via XML parser
        parser_events = self._parser.parse(response_text, self.tool_registry)

        # Extract thought, actions, and final answer from events
        thought_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        clean_text_parts: list[str] = []
        is_final = False

        for evt in parser_events:
            if evt.kind == "thought":
                thought_parts.append(evt.text)
                clean_text_parts.append(evt.text)
            elif evt.kind == "text":
                clean_text_parts.append(evt.text)
            elif evt.kind == "action":
                tc = ToolCall(name=evt.action_name, params=evt.action_input if isinstance(evt.action_input, dict) else {})
                tool_calls.append(tc)
            elif evt.kind == "final":
                is_final = True
                clean_text_parts.append(evt.text)

        thought = "\n".join(thought_parts) if thought_parts else ""
        clean_text = "\n".join(clean_text_parts).strip()

        if tool_calls:
            # Action found — update step with first action
            first = tool_calls[0]
            self._update_step_after_parse(
                step,
                thought=thought,
                action_name=first.name,
                action_input=dict(first.params),
                action_raw=response_text,
            )
        elif is_final or not tool_calls:
            # Final answer
            final_answer = clean_text or response_text.strip()
            self._update_step_after_parse(step, thought=thought)
            self._finalize_step(step, final_answer=final_answer)

        return StepResult(
            thought=thought,
            tool_calls=tool_calls,
            final_answer=clean_text if (is_final or not tool_calls) else "",
            clean_text=clean_text,
            raw_response=response_text,
            step=step,
        )

    def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM with retry, mirroring graph/nodes._call_llm."""
        io = self.coder.io
        text = ""
        for attempt in range(3):
            try:
                if self.coder.stream:
                    resp = self.model.send_completion(messages, stream=True)
                    chunks: list[str] = []
                    for chunk in resp:
                        if chunk.choices and chunk.choices[0].delta:
                            c = chunk.choices[0].delta.content
                            if c:
                                chunks.append(c)
                                io.print_streaming(c)
                    text = "".join(chunks)
                else:
                    text = self.model.simple_send(messages) or ""
                    if text:
                        io.print_assistant_output(text)
                break
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
        return text
