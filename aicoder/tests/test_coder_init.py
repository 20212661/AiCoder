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


def test_create_always_returns_base_coder():
    """Coder.create() must always return base Coder regardless of edit_format."""
    for fmt in ("whole", "diff", "ask", "architect"):
        coder = Coder.create(
            main_model=Model("machao-flash"),
            edit_format=fmt,
            io=InputOutput(pretty=False, yes=True),
        )
        assert type(coder) is Coder, f"edit_format={fmt} should produce base Coder, got {type(coder).__name__}"
        assert coder.edit_format == fmt


def test_edit_format_selects_prompts():
    """Different edit_format values should select different prompt templates."""
    io = InputOutput(pretty=False, yes=True)
    whole_coder = Coder.create(main_model=Model("machao-flash"), edit_format="whole", io=io)
    diff_coder = Coder.create(main_model=Model("machao-flash"), edit_format="diff", io=io)
    ask_coder = Coder.create(main_model=Model("machao-flash"), edit_format="ask", io=io)
    arch_coder = Coder.create(main_model=Model("machao-flash"), edit_format="architect", io=io)

    assert "developer" in whole_coder.gpt_prompts.main_system.lower()
    assert "developer" in diff_coder.gpt_prompts.main_system.lower()
    assert "analyst" in ask_coder.gpt_prompts.main_system.lower()
    assert "architect" in arch_coder.gpt_prompts.main_system.lower()


def test_show_announcements_displays_correct_mode_label():
    """show_announcements must show SNIFF/PLAN/ACT — not collapse sniff into PLAN."""
    io = InputOutput(pretty=False, yes=True)
    for mode, expected_label in [("act", "ACT"), ("plan", "PLAN"), ("sniff", "SNIFF")]:
        coder = Coder.create(main_model=Model("machao-flash"), edit_format="whole", io=io)
        coder.tool_executor.set_mode(mode)
        # Capture output
        lines: list[str] = []
        orig_output = coder.io.tool_output
        coder.io.tool_output = lambda msg, **kw: lines.append(msg)
        coder.show_announcements()
        coder.io.tool_output = orig_output
        joined = " ".join(lines)
        assert f"Mode: {expected_label}" in joined, (
            f"mode={mode} should display '{expected_label}', got: {joined}"
        )
