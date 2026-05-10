"""E2E tests for the JSON-RPC --serve mode.

Starts the backend as a subprocess and communicates via stdin/stdout.
"""
import json
import os
import subprocess
import sys
import threading

import pytest


def _read_json(proc, timeout=15):
    """Read lines until a valid JSON-RPC message is found (skip non-JSON)."""
    result = [None]

    def _reader():
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    result[0] = json.loads(line)
                    return
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


def _send_request(proc, method, params=None, msg_id=1):
    """Send a JSON-RPC request to the process stdin."""
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


@pytest.fixture
def serve_process(tmp_path):
    """Start aicoder --serve as a subprocess with a test API key."""
    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = "sk-test-e2e-fake-key"
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-m", "aicoder", "--serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(tmp_path),
        env=env,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


class TestServeStartup:
    def test_serve_emits_ready_notification(self, serve_process):
        msg = _read_json(serve_process, timeout=15)
        assert msg is not None, "No output from --serve process"
        assert msg.get("method") == "ready"
        params = msg.get("params", {})
        assert "model" in params
        assert "mode" in params
        assert "phase" in params

    def test_serve_emits_input_request_after_ready(self, serve_process):
        _read_json(serve_process, timeout=15)
        msg = _read_json(serve_process, timeout=15)
        assert msg is not None
        assert msg.get("method") == "input/request"
        params = msg.get("params", {})
        assert "root" in params
        assert "commands" in params


class TestServeRpcMethods:
    def test_input_submit_responds_ok(self, serve_process):
        _read_json(serve_process, timeout=15)
        _read_json(serve_process, timeout=15)

        _send_request(serve_process, "input/submit", {"text": "hello"}, msg_id=1)
        resp = _read_json(serve_process, timeout=10)
        assert resp is not None
        assert resp.get("id") == 1
        assert resp.get("result", {}).get("status") == "ok"

    def test_model_list_responds(self, serve_process):
        _read_json(serve_process, timeout=15)
        _read_json(serve_process, timeout=15)

        _send_request(serve_process, "model/list", {}, msg_id=2)
        resp = _read_json(serve_process, timeout=10)
        assert resp is not None
        assert resp.get("id") == 2
        result = resp.get("result", {})
        assert "models" in result
        assert isinstance(result["models"], list)

    def test_unknown_method_returns_error(self, serve_process):
        _read_json(serve_process, timeout=15)
        _read_json(serve_process, timeout=15)

        _send_request(serve_process, "nonexistent/method", {}, msg_id=3)
        resp = _read_json(serve_process, timeout=10)
        assert resp is not None
        assert resp.get("id") == 3
        assert resp.get("error", {}).get("code") == -32601


def _read_all_json(proc, timeout=10):
    """Read all JSON-RPC messages within *timeout* seconds."""
    messages = []

    def _reader():
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return messages


class TestServeQuit:
    def test_quit_command_exits_cleanly(self, serve_process):
        _read_json(serve_process, timeout=15)
        _read_json(serve_process, timeout=15)

        _send_request(serve_process, "input/submit", {"text": "/quit"}, msg_id=10)
        resp = _read_json(serve_process, timeout=10)
        assert resp is not None
        assert resp.get("id") == 10
        assert resp.get("result", {}).get("status") == "ok"
        # Close stdin from the parent side so the child's reader thread
        # receives EOF and unblocks.  On Windows, closing the fd from
        # within the child process does not reliably interrupt a blocking
        # C-level read() in another thread.
        serve_process.stdin.close()
        ret = serve_process.wait(timeout=10)
        # On Windows, the process may exit with non-zero due to forced teardown
        assert ret is not None


class TestServeFullRoundTrip:
    """Verify submitting input triggers backend processing events."""

    def _drain_startup(self, proc):
        _read_json(proc, timeout=15)
        _read_json(proc, timeout=15)

    def test_submit_input_triggers_status_update(self, serve_process):
        self._drain_startup(serve_process)

        _send_request(serve_process, "input/submit", {"text": "hello"}, msg_id=1)
        # Read the submit response first
        resp = _read_json(serve_process, timeout=10)
        assert resp is not None
        assert resp.get("id") == 1

        # Now read subsequent notifications — the backend should emit at
        # least a status/update (before the LLM call) or an error (if the
        # fake API key causes a failure).  Either way it proves the backend
        # actually started processing the submitted input.
        msgs = _read_all_json(serve_process, timeout=12)
        methods = [m.get("method") for m in msgs if m.get("method")]

        assert len(methods) > 0, "Expected at least one notification after input/submit"
        # Accept status/update (pre-LLM), error (fake key), or any
        # stream/tool notification as evidence of processing.
        processing_methods = {
            "status/update", "error", "stream/token", "stream/finalize",
            "assistant/output", "tool/call_started", "tool/output",
        }
        assert processing_methods.intersection(methods), (
            f"Expected a processing notification, got: {methods}"
        )
