"""Verification types — structured models for post-action checks.

Every verification round produces a list of VerificationResult objects.
These are consumed by:
  - graph nodes (to decide recovery)
  - event store (for persistence and replay)
  - debug / trace / dump (for observability)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

VerificationStatus = Literal["passed", "failed", "skipped", "error"]
VerificationLevel = Literal["light", "standard", "strict"]


@dataclass
class VerificationTask:
    """A single verification command to run after a tool execution.

    Typical tasks: lint check, type check, test subset, syntax check.
    """

    task_id: str
    name: str
    command: str
    required: bool = True
    timeout_ms: int = 120_000
    level: VerificationLevel = "standard"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "command": self.command,
            "required": self.required,
            "timeout_ms": self.timeout_ms,
            "level": self.level,
        }


@dataclass
class VerificationResult:
    """Outcome of a single verification task.

    status semantics:
      passed  — command exited 0
      failed  — command exited non-zero
      skipped — policy decided not to run this task
      error   — runner-level failure (timeout, OSError, etc.)
    """

    task_id: str
    status: VerificationStatus
    exit_code: int | None = None
    duration_ms: int = 0
    output_preview: str = ""
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "output_preview": self.output_preview,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VerificationResult:
        return cls(
            task_id=data["task_id"],
            status=data["status"],
            exit_code=data.get("exit_code"),
            duration_ms=data.get("duration_ms", 0),
            output_preview=data.get("output_preview", ""),
            error_message=data.get("error_message", ""),
        )


@dataclass
class VerificationRound:
    """Aggregated results from one verification pass (multiple tasks)."""

    results: list[VerificationResult] = field(default_factory=list)
    triggered_by: str = ""  # tool name or event that triggered this round

    @property
    def all_passed(self) -> bool:
        required = [r for r in self.results if r.status != "skipped"]
        return all(r.ok for r in required) if required else True

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.status == "error")

    @property
    def skip_count(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    def to_dict(self) -> dict:
        return {
            "results": [r.to_dict() for r in self.results],
            "triggered_by": self.triggered_by,
        }
