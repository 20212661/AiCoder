from aicoder.coders.base_coder import Coder
from aicoder.io import InputOutput
from aicoder.models import Model


def test_wholefile_coder_initializes_tool_state():
    coder = Coder.create(
        main_model=Model("machao-flash"),
        edit_format="whole",
        io=InputOutput(pretty=False, yes=True),
    )

    assert hasattr(coder, "tool_exec_state")
    assert hasattr(coder, "tool_executor")
    assert coder.tool_exec_state.is_plan_mode is False


class _SimpleModel(Model):
    def __init__(self):
        super().__init__("machao-flash")
        self.streaming = False

    def simple_send(self, messages):
        return "hello from assistant"


class _RepoSpy:
    def __init__(self):
        self.commit_calls = 0

    def get_head_commit_sha(self):
        return "abc1234"

    def get_tracked_files(self):
        return []

    def commit(self, *args, **kwargs):
        self.commit_calls += 1
        return None


def test_plain_chat_does_not_auto_commit():
    coder = Coder.create(
        main_model=_SimpleModel(),
        edit_format="whole",
        io=InputOutput(pretty=False, yes=True),
        auto_commits=True,
    )
    repo = _RepoSpy()
    coder.repo = repo

    coder.run_one("你好")

    assert repo.commit_calls == 0
