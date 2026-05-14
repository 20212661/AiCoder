"""
Architect Coder — DEPRECATED compatibility layer.

Coder.create() no longer dispatches to subclasses.  The prompts
(ArchitectPrompts) are still loaded by Coder._apply_edit_format_prompts(),
but this class is unreachable from the AgentRuntime execution path.

The two-model architect→editor pattern (reply_completed) was removed because
it passed unsupported kwargs (total_cost, from_coder) to Coder.create(),
causing TypeError.  If the pattern is needed again, it should be reimplemented
as a graph-level orchestration within AgentRuntime, not via Coder subclassing.
"""
from .ask_coder import AskCoder
from .architect_prompts import ArchitectPrompts


class ArchitectCoder(AskCoder):
    edit_format = "architect"
    gpt_prompts = ArchitectPrompts()
