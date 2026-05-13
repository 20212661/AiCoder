"""Tests for verification types and policy — Phase 1."""
import pytest

from aicoder.verification.types import (
    VerificationTask,
    VerificationResult,
    VerificationRound,
    VerificationLevel,
    VerificationStatus,
)
from aicoder.verification.policy import (
    VerificationPolicy,
    get_verification_level,
    get_builtin_tasks,
    select_verification_tasks,
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class TestVerificationTask:
    def test_to_dict_roundtrip(self):
        t = VerificationTask(
            task_id="lint", name="Lint", command="flake8 {files}",
            required=False, timeout_ms=60_000, level="standard",
        )
        d = t.to_dict()
        assert d["task_id"] == "lint"
        assert d["level"] == "standard"


class TestVerificationResult:
    def test_passed_ok(self):
        r = VerificationResult(task_id="t1", status="passed", exit_code=0)
        assert r.ok is True

    def test_failed_not_ok(self):
        r = VerificationResult(task_id="t1", status="failed", exit_code=1)
        assert r.ok is False

    def test_error_not_ok(self):
        r = VerificationResult(task_id="t1", status="error")
        assert r.ok is False

    def test_to_dict_from_dict_roundtrip(self):
        r = VerificationResult(
            task_id="t1", status="failed", exit_code=1,
            duration_ms=150, output_preview="E501 line too long",
        )
        d = r.to_dict()
        r2 = VerificationResult.from_dict(d)
        assert r2.task_id == r.task_id
        assert r2.status == r.status
        assert r2.exit_code == r.exit_code
        assert r2.duration_ms == r.duration_ms
        assert r2.output_preview == r.output_preview


class TestVerificationRound:
    def test_all_passed_true(self):
        round_ = VerificationRound(results=[
            VerificationResult(task_id="t1", status="passed"),
            VerificationResult(task_id="t2", status="passed"),
        ])
        assert round_.all_passed is True
        assert round_.pass_count == 2
        assert round_.fail_count == 0

    def test_all_passed_with_skips(self):
        round_ = VerificationRound(results=[
            VerificationResult(task_id="t1", status="passed"),
            VerificationResult(task_id="t2", status="skipped"),
        ])
        assert round_.all_passed is True
        assert round_.skip_count == 1

    def test_not_all_passed_with_failure(self):
        round_ = VerificationRound(results=[
            VerificationResult(task_id="t1", status="passed"),
            VerificationResult(task_id="t2", status="failed", exit_code=1),
        ])
        assert round_.all_passed is False
        assert round_.fail_count == 1

    def test_empty_round_passes(self):
        round_ = VerificationRound(results=[])
        assert round_.all_passed is True

    def test_error_count(self):
        round_ = VerificationRound(results=[
            VerificationResult(task_id="t1", status="error", error_message="timeout"),
            VerificationResult(task_id="t2", status="passed"),
        ])
        assert round_.error_count == 1

    def test_to_dict(self):
        round_ = VerificationRound(
            results=[VerificationResult(task_id="t1", status="passed")],
            triggered_by="edit_file",
        )
        d = round_.to_dict()
        assert d["triggered_by"] == "edit_file"
        assert len(d["results"]) == 1


# ---------------------------------------------------------------------------
# Policy: mode → level mapping
# ---------------------------------------------------------------------------


class TestGetVerificationLevel:
    def test_sniff_is_light(self):
        assert get_verification_level("sniff") == "light"

    def test_plan_is_light(self):
        assert get_verification_level("plan") == "light"

    def test_act_is_standard(self):
        assert get_verification_level("act") == "standard"

    def test_unknown_defaults_standard(self):
        assert get_verification_level("unknown") == "standard"


# ---------------------------------------------------------------------------
# Policy: VerificationPolicy
# ---------------------------------------------------------------------------


class TestVerificationPolicy:
    def test_default_uses_mode(self):
        p = VerificationPolicy()
        assert p.effective_level("act") == "standard"
        assert p.effective_level("sniff") == "light"

    def test_override_trumps_mode(self):
        p = VerificationPolicy(level_override="strict")
        assert p.effective_level("sniff") == "strict"
        assert p.effective_level("act") == "strict"

    def test_light_override(self):
        p = VerificationPolicy(level_override="light")
        assert p.effective_level("act") == "light"


# ---------------------------------------------------------------------------
# Policy: task selection
# ---------------------------------------------------------------------------


class TestSelectVerificationTasks:
    def test_act_mode_selects_standard_tasks(self):
        tasks = select_verification_tasks("act")
        task_ids = [t.task_id for t in tasks]
        # Standard level: syntax_check, import_check, lint, type_check
        assert "syntax_check" in task_ids
        assert "lint" in task_ids
        assert "type_check" in task_ids
        # Not strict: test_subset excluded
        assert "test_subset" not in task_ids

    def test_sniff_mode_selects_light_tasks(self):
        tasks = select_verification_tasks("sniff")
        task_ids = [t.task_id for t in tasks]
        # Light level: syntax_check, import_check
        assert "syntax_check" in task_ids
        assert "import_check" in task_ids
        assert "lint" not in task_ids

    def test_strict_override_selects_all(self):
        policy = VerificationPolicy(level_override="strict")
        tasks = select_verification_tasks("act", policy=policy)
        task_ids = [t.task_id for t in tasks]
        assert "test_subset" in task_ids
        assert "syntax_check" in task_ids
        assert "lint" in task_ids

    def test_blocked_tasks_excluded(self):
        policy = VerificationPolicy(blocked_tasks=frozenset({"lint"}))
        tasks = select_verification_tasks("act", policy=policy)
        task_ids = [t.task_id for t in tasks]
        assert "lint" not in task_ids
        assert "syntax_check" in task_ids

    def test_allowed_tasks_filter(self):
        policy = VerificationPolicy(allowed_tasks=frozenset({"syntax_check"}))
        tasks = select_verification_tasks("act", policy=policy)
        task_ids = [t.task_id for t in tasks]
        assert task_ids == ["syntax_check"]

    def test_no_matching_files_returns_empty(self):
        tasks = select_verification_tasks(
            "act", changed_files=["readme.md", "image.png"],
        )
        assert tasks == []

    def test_python_files_trigger_tasks(self):
        tasks = select_verification_tasks(
            "act", changed_files=["main.py"],
        )
        assert len(tasks) > 0

    def test_js_files_trigger_tasks(self):
        tasks = select_verification_tasks(
            "act", changed_files=["app.js"],
        )
        assert len(tasks) > 0

    def test_extra_tasks_included(self):
        extra = VerificationTask(
            task_id="custom", name="Custom", command="echo ok", level="light",
        )
        tasks = select_verification_tasks("sniff", extra_tasks=[extra])
        task_ids = [t.task_id for t in tasks]
        assert "custom" in task_ids

    def test_extra_tasks_filtered_by_level(self):
        extra = VerificationTask(
            task_id="heavy", name="Heavy", command="pytest", level="strict",
        )
        tasks = select_verification_tasks("sniff", extra_tasks=[extra])
        task_ids = [t.task_id for t in tasks]
        assert "heavy" not in task_ids

    def test_none_changed_files_selects_tasks(self):
        """When changed_files is None, tasks should still be selected."""
        tasks = select_verification_tasks("act", changed_files=None)
        assert len(tasks) > 0


# ---------------------------------------------------------------------------
# Builtin tasks
# ---------------------------------------------------------------------------


class TestBuiltinTasks:
    def test_builtin_tasks_exist(self):
        tasks = get_builtin_tasks()
        assert len(tasks) >= 3
        ids = [t.task_id for t in tasks]
        assert "syntax_check" in ids
        assert "lint" in ids

    def test_builtin_tasks_have_valid_levels(self):
        for t in get_builtin_tasks():
            assert t.level in ("light", "standard", "strict")


# ---------------------------------------------------------------------------
# Debounce / suppression
# ---------------------------------------------------------------------------


class TestVerificationDebounce:
    """Tests for verification debounce — same task, short window, suppress."""

    def test_should_suppress_returns_true_for_recent_failure(self):
        """When a task failed recently in the same iteration, it should be suppressed."""
        from aicoder.verification.policy import should_suppress_verification

        recent_results = [
            {"task_id": "syntax_check", "status": "failed", "iteration": 0},
        ]
        assert should_suppress_verification("syntax_check", 0, recent_results) is True

    def test_should_not_suppress_different_iteration(self):
        """Different iteration means the failure is stale, don't suppress."""
        from aicoder.verification.policy import should_suppress_verification

        recent_results = [
            {"task_id": "syntax_check", "status": "failed", "iteration": 0},
        ]
        assert should_suppress_verification("syntax_check", 1, recent_results) is False

    def test_should_not_suppress_passed_task(self):
        """A passed task doesn't need suppression."""
        from aicoder.verification.policy import should_suppress_verification

        recent_results = [
            {"task_id": "syntax_check", "status": "passed", "iteration": 0},
        ]
        assert should_suppress_verification("syntax_check", 0, recent_results) is False

    def test_should_not_suppress_unknown_task(self):
        """No prior result means no suppression."""
        from aicoder.verification.policy import should_suppress_verification

        assert should_suppress_verification("lint", 0, []) is False

    def test_should_not_suppress_different_task(self):
        """Different task_id means independent failure."""
        from aicoder.verification.policy import should_suppress_verification

        recent_results = [
            {"task_id": "syntax_check", "status": "failed", "iteration": 0},
        ]
        assert should_suppress_verification("lint", 0, recent_results) is False
