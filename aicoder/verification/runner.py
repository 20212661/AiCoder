"""Verification runner — execute verification tasks and collect results.

Runs each selected task as a subprocess, enforces timeout, and returns
structured VerificationRound results.  Never raises into the caller;
failures are captured as VerificationResult(status="error").
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .types import VerificationResult, VerificationRound, VerificationTask


def run_verification_tasks(
    tasks: list[VerificationTask],
    root: str = ".",
    changed_files: list[str] | None = None,
) -> VerificationRound:
    """Execute verification tasks sequentially and return aggregated results.

    Args:
        tasks: Ordered list of tasks to execute.
        root: Working directory for subprocess execution.
        changed_files: Files that triggered verification (for command templating).

    Returns:
        VerificationRound with one VerificationResult per task.
    """
    results: list[VerificationResult] = []
    for task in tasks:
        result = _run_single_task(task, root, changed_files)
        results.append(result)
        # Stop early if a required task fails (but don't crash)
        if not result.ok and task.required:
            # Still run remaining tasks but skip non-required ones
            continue
    return VerificationRound(results=results)


def _run_single_task(
    task: VerificationTask,
    root: str,
    changed_files: list[str] | None,
) -> VerificationResult:
    """Run a single verification task as a subprocess."""
    command = _resolve_command(task.command, root, changed_files)
    cwd = str(Path(root).resolve())

    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=task.timeout_ms / 1000,
            cwd=cwd,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        output = (proc.stdout + proc.stderr).strip()

        if proc.returncode == 0:
            return VerificationResult(
                task_id=task.task_id,
                status="passed",
                exit_code=0,
                duration_ms=duration_ms,
                output_preview=_truncate(output, 500),
            )
        return VerificationResult(
            task_id=task.task_id,
            status="failed",
            exit_code=proc.returncode,
            duration_ms=duration_ms,
            output_preview=_truncate(output, 500),
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        return VerificationResult(
            task_id=task.task_id,
            status="error",
            duration_ms=duration_ms,
            error_message=f"Timeout after {task.timeout_ms}ms",
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return VerificationResult(
            task_id=task.task_id,
            status="error",
            duration_ms=duration_ms,
            error_message=str(exc),
        )


def _resolve_command(
    template: str,
    root: str,
    changed_files: list[str] | None,
) -> str:
    """Substitute placeholders in command template."""
    files_str = " ".join(changed_files) if changed_files else ""
    modules_str = _extract_modules(changed_files)

    cmd = template
    cmd = cmd.replace("{files}", files_str)
    cmd = cmd.replace("{modules}", modules_str)
    cmd = cmd.replace("{root}", root)

    # Resolve test_files: for each source file, look for test_*.py or *_test.py
    if "{test_files}" in cmd:
        test_files = _resolve_test_files(root, changed_files)
        cmd = cmd.replace("{test_files}", " ".join(test_files))

    return cmd


def _extract_modules(files: list[str] | None) -> str:
    """Derive module import names from file paths."""
    if not files:
        return ""
    modules = []
    for f in files:
        p = Path(f)
        if p.suffix == ".py":
            mod = str(p.with_suffix("")).replace("/", ".").replace("\\", ".")
            if mod:
                modules.append(mod)
    return ", ".join(modules)


def _resolve_test_files(root: str, files: list[str] | None) -> list[str]:
    """Find test files corresponding to changed source files."""
    if not files:
        return []
    test_files: list[str] = []
    root_path = Path(root)
    for f in files:
        p = Path(f)
        if p.suffix != ".py":
            continue
        # Try common test file naming conventions
        stem = p.stem
        parent = p.parent
        candidates = [
            parent / f"test_{stem}.py",
            parent / f"{stem}_test.py",
            parent / "tests" / f"test_{stem}.py",
            parent / "test" / f"test_{stem}.py",
        ]
        for c in candidates:
            full = root_path / c
            if full.exists():
                test_files.append(str(c))
                break
    return test_files


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
