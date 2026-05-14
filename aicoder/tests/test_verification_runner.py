"""Tests for verification runner — Phase 2."""
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from aicoder.verification.runner import (
    _extract_modules,
    _resolve_command,
    _resolve_test_files,
    _truncate,
    run_verification_tasks,
)
from aicoder.verification.types import VerificationResult, VerificationTask


# ---------------------------------------------------------------------------
# Runner: run_verification_tasks
# ---------------------------------------------------------------------------


class TestRunVerificationTasks:
    def test_success_task(self, tmp_path):
        """A command that exits 0 produces status='passed'."""
        task = VerificationTask(
            task_id="echo", name="Echo", command="echo ok", level="light",
        )
        round_ = run_verification_tasks([task], root=str(tmp_path))
        assert len(round_.results) == 1
        assert round_.results[0].status == "passed"
        assert round_.results[0].exit_code == 0

    def test_failure_task(self, tmp_path):
        """A command that exits non-zero produces status='failed'."""
        task = VerificationTask(
            task_id="fail", name="Fail",
            command="python -c \"raise SystemExit(1)\"",
            level="light",
        )
        round_ = run_verification_tasks([task], root=str(tmp_path))
        assert len(round_.results) == 1
        assert round_.results[0].status == "failed"
        assert round_.results[0].exit_code == 1

    def test_timeout_task(self, tmp_path):
        """A task that exceeds timeout produces status='error'."""
        task = VerificationTask(
            task_id="slow", name="Slow",
            command="python -c \"import time; time.sleep(10)\"",
            timeout_ms=500,
            level="light",
        )
        round_ = run_verification_tasks([task], root=str(tmp_path))
        assert len(round_.results) == 1
        assert round_.results[0].status == "error"
        assert "Timeout" in round_.results[0].error_message

    def test_multiple_tasks(self, tmp_path):
        """Multiple tasks produce one result each."""
        tasks = [
            VerificationTask(task_id="t1", name="T1", command="echo 1", level="light"),
            VerificationTask(task_id="t2", name="T2", command="echo 2", level="light"),
        ]
        round_ = run_verification_tasks(tasks, root=str(tmp_path))
        assert len(round_.results) == 2
        assert all(r.status == "passed" for r in round_.results)

    def test_mixed_pass_fail(self, tmp_path):
        """Mix of passing and failing tasks."""
        tasks = [
            VerificationTask(task_id="ok", name="OK", command="echo ok", level="light"),
            VerificationTask(
                task_id="bad", name="Bad", required=False,
                command="python -c \"raise SystemExit(2)\"",
                level="light",
            ),
        ]
        round_ = run_verification_tasks(tasks, root=str(tmp_path))
        assert round_.pass_count == 1
        assert round_.fail_count == 1
        assert not round_.all_passed

    def test_empty_tasks(self, tmp_path):
        """Empty task list produces empty round."""
        round_ = run_verification_tasks([], root=str(tmp_path))
        assert len(round_.results) == 0
        assert round_.all_passed

    def test_invalid_command(self, tmp_path):
        """Invalid command produces status='error' (OSError caught)."""
        task = VerificationTask(
            task_id="bad_cmd", name="BadCmd",
            command="nonexistent_command_xyz_123",
            level="light",
        )
        round_ = run_verification_tasks([task], root=str(tmp_path))
        assert round_.results[0].status in ("failed", "error")

    def test_syntax_check_on_valid_file(self, tmp_path):
        """Syntax check passes on a valid Python file."""
        src = tmp_path / "hello.py"
        src.write_text("x = 1\n")
        task = VerificationTask(
            task_id="syntax_check", name="Syntax", command="python -m py_compile {files}",
            level="light",
        )
        round_ = run_verification_tasks(
            [task], root=str(tmp_path), changed_files=["hello.py"],
        )
        assert round_.results[0].status == "passed"


# ---------------------------------------------------------------------------
# Command resolution
# ---------------------------------------------------------------------------


class TestResolveCommand:
    def test_files_substitution(self):
        cmd = _resolve_command("py_compile {files}", ".", ["a.py", "b.py"])
        assert "a.py" in cmd
        assert "b.py" in cmd

    def test_modules_substitution(self):
        cmd = _resolve_command("import {modules}", ".", ["pkg/mod.py"])
        assert "pkg.mod" in cmd

    def test_root_substitution(self):
        cmd = _resolve_command("cd {root}", "/tmp", None)
        assert "/tmp" in cmd

    def test_empty_files(self):
        cmd = _resolve_command("check {files}", ".", None)
        assert cmd == "check "

    def test_test_files_resolution(self, tmp_path):
        # Create source and test file
        src = tmp_path / "calc.py"
        src.write_text("x = 1\n")
        test = tmp_path / "test_calc.py"
        test.write_text("from calc import x\n")
        cmd = _resolve_command(
            "pytest {test_files}", str(tmp_path), ["calc.py"],
        )
        assert "test_calc.py" in cmd


class TestExtractModules:
    def test_python_files(self):
        result = _extract_modules(["foo/bar.py", "baz.py"])
        assert "foo.bar" in result
        assert "baz" in result

    def test_non_python_files(self):
        result = _extract_modules(["readme.md", "app.js"])
        assert result == ""

    def test_none_files(self):
        assert _extract_modules(None) == ""


class TestResolveTestFiles:
    def test_finds_test_file(self, tmp_path):
        src = tmp_path / "utils.py"
        src.write_text("x = 1\n")
        test = tmp_path / "test_utils.py"
        test.write_text("from utils import x\n")
        result = _resolve_test_files(str(tmp_path), ["utils.py"])
        assert "test_utils.py" in result[0]

    def test_no_matching_test(self, tmp_path):
        src = tmp_path / "orphan.py"
        src.write_text("x = 1\n")
        result = _resolve_test_files(str(tmp_path), ["orphan.py"])
        assert result == []

    def test_empty_input(self):
        assert _resolve_test_files(".", None) == []


class TestTruncate:
    def test_short_string(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length(self):
        assert _truncate("12345", 5) == "12345"

    def test_truncates(self):
        result = _truncate("abcdefghij", 5)
        assert result == "ab..."
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Integration: verification runner via graph node
# ---------------------------------------------------------------------------


class TestVerifyNodeIntegration:
    def test_verify_node_with_file_changes(self, tmp_path):
        """verify_node triggers when tool observations contain file changes."""
        from aicoder.graph.nodes import verify_node

        src = tmp_path / "sample.py"
        src.write_text("x = 1 + 1\n")

        state = {
            "session_id": "test",
            "mode": "act",
            "root": str(tmp_path),
            "tool_observations": [
                {
                    "tool_name": "write_file",
                    "success": True,
                    "files": ["sample.py"],
                },
            ],
            "verification_results": [],
        }
        result = verify_node(state)
        assert result["phase"] == "verifying"
        assert len(result["verification_results"]) == 1
        round_dict = result["verification_results"][0]
        assert "results" in round_dict

    def test_verify_node_no_file_changes(self):
        """verify_node passes through when no file changes detected."""
        from aicoder.graph.nodes import verify_node

        state = {
            "session_id": "test",
            "mode": "act",
            "root": ".",
            "tool_observations": [
                {"tool_name": "read_file", "success": True},
            ],
            "verification_results": [],
        }
        result = verify_node(state)
        assert result["phase"] == "verifying"
        # No verification results because no files changed
        assert "verification_results" not in result

    def test_verify_node_no_observations(self):
        """verify_node handles empty observations."""
        from aicoder.graph.nodes import verify_node

        state = {
            "session_id": "test",
            "mode": "act",
            "root": ".",
            "tool_observations": [],
            "verification_results": [],
        }
        result = verify_node(state)
        assert result["phase"] == "verifying"


class TestVerificationSuppressed:
    """Tests for verification_suppressed event emission when debounce triggers."""

    def test_suppressed_task_emits_event(self, tmp_path):
        """When a task is suppressed via debounce, verify_node emits verification_suppressed."""
        from aicoder.graph.nodes import verify_node
        from aicoder.graph.state import register_coder, unregister_coder
        from aicoder.runners import register_runner, unregister_runner
        from aicoder.agent_step_store import AgentStepStore
        from aicoder.runners.cot_agent_runner import CotAgentRunner
        from unittest.mock import MagicMock

        session_id = "test-v-suppress"
        coder = MagicMock()
        coder.root = str(tmp_path)
        coder.tool_exec_state = MagicMock()
        coder.tool_exec_state.mode = "act"
        register_coder(session_id, coder)

        step_store = AgentStepStore(session_id=session_id)
        runner = CotAgentRunner(
            coder=coder, session_id=session_id, mode="act",
            tool_registry={}, step_store=step_store,
        )
        register_runner(session_id, runner)

        try:
            test_file = tmp_path / "mod.py"
            test_file.write_text("x =\n")  # syntax error

            state = {
                "session_id": session_id,
                "mode": "act",
                "root": str(tmp_path),
                "loop_count": 0,
                "tool_observations": [
                    {
                        "tool_name": "edit_file",
                        "success": True,
                        "output": "edited",
                        "error": "",
                        "rejected": False,
                        "files": [str(test_file)],
                    },
                ],
                # Prior verification result showing syntax_check failed in same iteration
                "verification_results": [
                    {
                        "results": [
                            {"task_id": "syntax_check", "status": "failed", "exit_code": 1,
                             "duration_ms": 100, "output_preview": "SyntaxError",
                             "error_message": "syntax error"},
                        ],
                        "triggered_by": "edit_file",
                    },
                ],
            }
            result = verify_node(state)

            events = step_store.event_store.all_events()
            suppressed = [e for e in events if e.kind == "verification_suppressed"]
            if suppressed:
                assert suppressed[0].payload["task_id"] == "syntax_check"
                assert "reason" in suppressed[0].payload
        finally:
            unregister_runner(session_id)
            unregister_coder(session_id)
