"""
Context window manager — multi-level degradation strategy.

Modeled after Cline's ContextManager with tiered fallback:
  1. File-read cache (preventive)  — skip re-reading unchanged files
  2. Proactive truncation           — trim old messages when near limit
  3. Aggressive truncation          — quarter-mode when half isn't enough
  4. Emergency truncation           — on context_window_exceeded API error

All levels share a percentage-based threshold system keyed to the model's
context window size.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Token budget thresholds (percentage of context window)
# ---------------------------------------------------------------------------

@dataclass
class Thresholds:
    """Percentage thresholds applied to the model's context window."""
    soft: float = 0.70       # trigger proactive truncation at 70 %
    hard: float = 0.85       # trigger aggressive truncation at 85 %
    emergency: float = 0.95  # emergency on API error at 95 %


# Reserve buffers (absolute tokens subtracted before computing budget)
RESERVE_BUFFERS: dict[int, int] = {
    64_000: 27_000,   # ~64K  models
    128_000: 30_000,  # ~128K models
    200_000: 40_000,  # ~200K models
}


def _reserve_buffer(window: int) -> int:
    """Pick the closest reserve buffer for a given context window."""
    best = 4_096
    for cap, buf in sorted(RESERVE_BUFFERS.items()):
        if window >= cap:
            best = buf
    return best


def _effective_window(max_input_tokens: int) -> int:
    return max(1024, max_input_tokens - _reserve_buffer(max_input_tokens))


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@dataclass
class ContextSnapshot:
    """Result of a context-window operation."""
    messages: list[dict]
    total_tokens: int
    truncated: bool
    deleted_count: int              # messages removed from the front
    strategy: str                   # "none" | "soft" | "hard" | "emergency"


class ContextManager:
    """Multi-level context window manager for a single conversation."""

    def __init__(
        self,
        token_counter: callable,         # (messages) -> int
        max_input_tokens: int = 131_072,
        thresholds: Thresholds | None = None,
    ):
        self._token_count = token_counter
        self._max_input_tokens = max_input_tokens
        self._effective = _effective_window(max_input_tokens)
        self._thresholds = thresholds or Thresholds()

        # Track previous truncation so we can escalate
        self._last_strategy: str = "none"
        self._total_deleted: int = 0

    # ---- public API --------------------------------------------------------

    def prepare_messages(
        self,
        all_messages: list[dict],
        system_messages: list[dict] | None = None,
        force_strategy: str | None = None,
    ) -> ContextSnapshot:
        """Return a (possibly truncated) message list ready for the API."""
        if not all_messages:
            return ContextSnapshot([], 0, False, 0, "none")

        total = self._safe_token_count(all_messages)
        limit = self._effective

        # Determine strategy
        if force_strategy:
            strategy = force_strategy
        elif total <= limit * self._thresholds.soft:
            strategy = "none"
        elif total <= limit * self._thresholds.hard:
            strategy = "soft"
        elif total <= limit * self._thresholds.emergency:
            strategy = "hard"
        else:
            strategy = "emergency"

        if strategy == "none":
            return ContextSnapshot(list(all_messages), total, False, 0, strategy)

        # Truncate from the front
        keep_ratio = 0.5 if strategy in ("soft",) else 0.25
        keep_count = max(2, int(len(all_messages) * keep_ratio))

        # Ensure we end on an assistant message
        kept = all_messages[-keep_count:]
        while len(kept) > 1 and kept[0].get("role") != "assistant":
            kept = kept[1:]

        deleted = len(all_messages) - len(kept)
        self._total_deleted += deleted
        self._last_strategy = strategy

        # Insert a truncation notice at the front
        notice = self._truncation_notice(deleted)
        result = [notice] + kept

        new_total = self._safe_token_count(result)
        return ContextSnapshot(result, new_total, True, deleted, strategy)

    def handle_context_window_exceeded(self, all_messages: list[dict]) -> ContextSnapshot:
        """Called when the API returns a context_window_exceeded error."""
        return self.prepare_messages(all_messages, force_strategy="emergency")

    @property
    def last_strategy(self) -> str:
        return self._last_strategy

    @property
    def total_deleted(self) -> int:
        return self._total_deleted

    # ---- internals ---------------------------------------------------------

    def _safe_token_count(self, messages: list[dict]) -> int:
        try:
            return self._token_count(messages)
        except Exception:
            # Fallback: rough char-based estimate
            total = 0
            for m in messages:
                if isinstance(m, dict):
                    total += len(str(m.get("content", "")))
                else:
                    total += len(str(m))
            return max(1, total // 4)

    @staticmethod
    def _truncation_notice(deleted_count: int) -> dict:
        return {
            "role": "user",
            "content": (
                f"[CONTEXT TRUNCATED]  {deleted_count} earlier messages were "
                f"removed to stay within the context window.  The conversation "
                f"below continues from the most recent messages."
            ),
        }
