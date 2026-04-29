from aicoder.message_pipeline import UiEvent, transform_events


def test_groups_low_stakes_tools():
    events = [
        UiEvent(kind="tool", tool_name="read_file", phase="finish", success=True, params={"path": "src/app.py"}),
        UiEvent(kind="tool", tool_name="list_files", phase="finish", success=True, params={"path": "src"}),
        UiEvent(kind="tool", tool_name="search_files", phase="finish", success=True, params={"path": ".", "regex": "main"}),
    ]

    nodes = transform_events(events)

    assert len(nodes) == 1
    assert nodes[0].kind == "tool_group"
    assert "AiCoder" in nodes[0].title
    assert len(nodes[0].items) == 3


def test_command_renders_as_command_node():
    events = [
        UiEvent(
            kind="tool",
            tool_name="run_shell",
            phase="finish",
            success=True,
            params={"command": "npm test"},
            output="Exit: 0  Time: 1.0s\n\nok",
        )
    ]

    nodes = transform_events(events)

    assert len(nodes) == 1
    assert nodes[0].kind == "command"
    assert "npm test" in nodes[0].title


def test_edit_result_renders_as_diff_node():
    events = [
        UiEvent(
            kind="tool",
            tool_name="edit_file",
            phase="finish",
            success=True,
            params={"path": "src/app.py"},
            output="Updated src/app.py",
            meta={"path": "src/app.py", "action": "Updated", "diff": "--- a\n+++ b\n@@\n-x\n+y"},
        )
    ]

    nodes = transform_events(events)

    assert len(nodes) == 1
    assert nodes[0].kind == "diff"
    assert "src/app.py" in nodes[0].title
