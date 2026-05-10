from unittest.mock import MagicMock, patch

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


def test_coder_run_delegates_to_agent_runtime():
    """Verify Coder.run(with_message=...) creates runtime and delegates."""
    coder = Coder.create(
        main_model=Model("machao-flash"),
        edit_format="whole",
        io=InputOutput(pretty=False, yes=True),
    )

    fake_runtime = MagicMock()
    fake_runtime.run_user_turn.return_value = "ok-from-runtime"

    with patch("aicoder.agent_runtime._create_runtime", return_value=fake_runtime) as mock_factory:
        result = coder.run(with_message="hello")

    mock_factory.assert_called_once_with(coder)
    fake_runtime.run_user_turn.assert_called_once_with("hello")
    assert result == "ok-from-runtime"
