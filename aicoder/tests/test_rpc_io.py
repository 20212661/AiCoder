from queue import Queue
from unittest.mock import MagicMock

from aicoder.rpc_io import JsonRpcIO


class _FakeQueue:
    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.return_value


def test_get_input_blocks_without_idle_timeout():
    io = JsonRpcIO()
    fake_queue = _FakeQueue("hello from tui")
    io._input_queue = fake_queue
    io._notify = MagicMock()

    result = io.get_input(
        root="D:/CodingProject/aiCoder",
        inchat_files=[],
        addable_files=[],
        commands=["/help"],
        read_only_fnames=[],
    )

    assert result == "hello from tui"
    assert fake_queue.calls == [((), {})]
    io._notify.assert_called_once()


def test_get_input_returns_queued_command_immediately():
    io = JsonRpcIO()
    io._input_queue = Queue()
    io._input_queue.put("/quit")
    io._notify = MagicMock()

    result = io.get_input(
        root="D:/CodingProject/aiCoder",
        inchat_files=[],
        addable_files=[],
        commands=["/quit"],
        read_only_fnames=[],
    )

    assert result == "/quit"
    io._notify.assert_called_once()
