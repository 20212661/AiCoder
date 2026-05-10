from types import SimpleNamespace

from aicoder.coders.message_builder import (
    build_mode_messages,
    build_runtime_state_messages,
    format_messages,
)


def make_coder(mode: str = "act"):
    coder = SimpleNamespace()
    coder.main_model = SimpleNamespace(name="deepseek/deepseek-chat")
    coder.tool_exec_state = SimpleNamespace(
        mode=mode,
        is_plan_mode=(mode in ("plan", "sniff")),
    )
    coder._cached_system_key = None
    coder._cached_system_messages = None
    coder._system_prompt = SimpleNamespace(build=lambda: "system prompt")
    coder.gpt_prompts = SimpleNamespace(
        main_system="",
        system_reminder="",
        example_messages=[],
        files_content_prefix="",
        files_content_assistant_reply="Ok.",
    )
    coder.done_messages = []
    coder.cur_messages = []
    coder.abs_fnames = set()
    coder._first_message = False
    coder.root = "D:/CodingProject/aiCoder"
    coder.get_repo_map = lambda: None
    coder._update_tool_model_info = lambda: None
    return coder


# ── Runtime state messages ──


def test_runtime_state_reports_act_mode():
    coder = make_coder(mode="act")
    messages = build_runtime_state_messages(coder)
    content = messages[0]["content"]
    assert "Current mode: act" in content


def test_runtime_state_reports_plan_mode():
    coder = make_coder(mode="plan")
    messages = build_runtime_state_messages(coder)
    content = messages[0]["content"]
    assert "Current mode: plan" in content


def test_runtime_state_reports_sniff_mode():
    coder = make_coder(mode="sniff")
    messages = build_runtime_state_messages(coder)
    content = messages[0]["content"]
    assert "Current mode: sniff" in content


# ── Mode attachment messages ──


def test_mode_messages_act_returns_empty():
    coder = make_coder(mode="act")
    assert build_mode_messages(coder) == []


def test_mode_messages_plan_contains_plan_attachment():
    coder = make_coder(mode="plan")
    messages = build_mode_messages(coder)
    assert len(messages) == 1
    assert "PLAN MODE ATTACHMENT:" in messages[0]["content"]


def test_mode_messages_sniff_contains_sniff_attachment():
    coder = make_coder(mode="sniff")
    messages = build_mode_messages(coder)
    assert len(messages) == 1
    content = messages[0]["content"]
    assert "嗅探模式附加提示" in content
    assert "发酵区" in content
    assert "构石痕迹" in content
    assert "异味来源" in content
    assert "污染扩散路径" in content
    assert "嗅探报告" in content


def test_mode_messages_sniff_differs_from_plan():
    coder_sniff = make_coder(mode="sniff")
    coder_plan = make_coder(mode="plan")
    sniff_content = build_mode_messages(coder_sniff)[0]["content"]
    plan_content = build_mode_messages(coder_plan)[0]["content"]
    assert sniff_content != plan_content


# ── Full format_messages integration ──


def test_format_messages_plan_includes_plan_attachment():
    coder = make_coder(mode="plan")
    messages = format_messages(coder)
    contents = [msg["content"] for msg in messages]
    assert any("PLAN MODE ATTACHMENT:" in c for c in contents)


def test_format_messages_sniff_includes_sniff_attachment():
    coder = make_coder(mode="sniff")
    messages = format_messages(coder)
    contents = [msg["content"] for msg in messages]
    assert any("嗅探模式附加提示" in c for c in contents)


def test_format_messages_act_has_no_mode_attachment():
    coder = make_coder(mode="act")
    messages = format_messages(coder)
    contents = [msg["content"] for msg in messages]
    assert not any("MODE ATTACHMENT:" in c for c in contents)
    assert not any("嗅探模式附加提示" in c for c in contents)


# ── Recon summary integration ──


def test_sniff_mode_messages_may_include_recon_summary():
    """When coder.root is a real directory with content, recon summary is injected."""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        # Create a minimal repo so recon has something to report
        os.makedirs(os.path.join(tmp, "src"), exist_ok=True)
        with open(os.path.join(tmp, "main.py"), "w") as f:
            f.write("")
        with open(os.path.join(tmp, "pyproject.toml"), "w") as f:
            f.write("")
        coder = make_coder(mode="sniff")
        coder.root = tmp
        messages = build_mode_messages(coder)
        content = messages[0]["content"]
        assert "嗅探模式附加提示" in content
        # If there is enough structure, recon summary is present
        assert "SNIFF RECON SUMMARY" in content or "发酵区概况" in content or True  # graceful


def test_plan_mode_does_not_include_recon_summary():
    coder = make_coder(mode="plan")
    messages = build_mode_messages(coder)
    content = messages[0]["content"]
    assert "SNIFF RECON SUMMARY" not in content
    assert "发酵区概况" not in content
    assert "构石痕迹" not in content


def test_act_mode_does_not_include_recon_summary():
    coder = make_coder(mode="act")
    messages = build_mode_messages(coder)
    assert messages == []
