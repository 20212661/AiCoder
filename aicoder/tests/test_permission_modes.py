from aicoder.approval import ApprovalController, AutoApprovalSettings
from aicoder.permission_modes import (
    ToolPermissionContext,
    can_use_tool_in_mode,
    get_visible_tool_specs,
)
from aicoder.tools.spec import ParamSpec, ToolSpec


def test_plan_mode_hides_edit_tools():
    tools = [
        ToolSpec(name="read_file", description="Read", parameters=[ParamSpec(name="path")]),
        ToolSpec(name="edit_file", description="Edit", parameters=[ParamSpec(name="path")]),
        ToolSpec(name="run_shell", description="Run", parameters=[ParamSpec(name="command")]),
    ]

    visible = get_visible_tool_specs(tools, "plan")

    assert [tool.name for tool in visible] == ["read_file", "run_shell"]


def test_plan_mode_denies_file_edits():
    decision = can_use_tool_in_mode(
        "edit_file",
        {"path": "main.py"},
        ToolPermissionContext(mode="plan"),
        ApprovalController(),
    )

    assert decision.behavior == "deny"
    assert "read-only" in decision.reason.lower()


def test_plan_mode_allows_safe_shell_reads():
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=True))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "git status"},
        ToolPermissionContext(mode="plan"),
        approval,
    )

    assert decision.behavior == "allow"


def test_plan_mode_denies_mutating_shell_commands():
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=True))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "python manage.py migrate"},
        ToolPermissionContext(mode="plan"),
        approval,
    )

    assert decision.behavior == "deny"
    assert "shell" in decision.reason.lower()


def test_act_mode_auto_allows_file_edits():
    decision = can_use_tool_in_mode(
        "write_file",
        {"path": "main.py", "content": "print('x')"},
        ToolPermissionContext(mode="act"),
        ApprovalController(),
    )

    assert decision.behavior == "ask"


def test_act_mode_auto_allows_safe_shell_commands():
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=True))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "git status"},
        ToolPermissionContext(mode="act"),
        approval,
    )

    assert decision.behavior == "allow"


def test_act_mode_rm_requires_approval():
    """rm was removed from ACT_MODE_AUTO_APPROVED_COMMANDS — must ask."""
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=False))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "rm temp.log"},
        ToolPermissionContext(mode="act"),
        approval,
    )
    assert decision.behavior == "ask"


def test_act_mode_mv_requires_approval():
    """mv was removed from ACT_MODE_AUTO_APPROVED_COMMANDS — must ask."""
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=False))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "mv old.py new.py"},
        ToolPermissionContext(mode="act"),
        approval,
    )
    assert decision.behavior == "ask"


def test_act_mode_sed_requires_approval():
    """sed was removed from ACT_MODE_AUTO_APPROVED_COMMANDS — must ask."""
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=False))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "sed -i 's/old/new/g' file.txt"},
        ToolPermissionContext(mode="act"),
        approval,
    )
    assert decision.behavior == "ask"


def test_act_mode_mkdir_auto_approved():
    """mkdir remains in ACT_MODE_AUTO_APPROVED_COMMANDS."""
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=False))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "mkdir new_dir"},
        ToolPermissionContext(mode="act"),
        approval,
    )
    assert decision.behavior == "allow"


# ── SNIFF MODE TESTS ──


def test_sniff_mode_hides_edit_tools():
    tools = [
        ToolSpec(name="read_file", description="Read", parameters=[ParamSpec(name="path")]),
        ToolSpec(name="edit_file", description="Edit", parameters=[ParamSpec(name="path")]),
        ToolSpec(name="run_shell", description="Run", parameters=[ParamSpec(name="command")]),
    ]

    visible = get_visible_tool_specs(tools, "sniff")

    assert [tool.name for tool in visible] == ["read_file", "run_shell"]


def test_sniff_mode_denies_file_edits():
    decision = can_use_tool_in_mode(
        "edit_file",
        {"path": "main.py"},
        ToolPermissionContext(mode="sniff"),
        ApprovalController(),
    )

    assert decision.behavior == "deny"
    assert "SNIFF" in decision.reason


def test_sniff_mode_denies_file_writes():
    decision = can_use_tool_in_mode(
        "write_file",
        {"path": "main.py", "content": "print('x')"},
        ToolPermissionContext(mode="sniff"),
        ApprovalController(),
    )

    assert decision.behavior == "deny"


def test_sniff_mode_allows_read_tools():
    for tool in ["read_file", "search_files", "list_files", "list_code_defs"]:
        decision = can_use_tool_in_mode(
            tool,
            {},
            ToolPermissionContext(mode="sniff"),
            ApprovalController(),
        )
        assert decision.behavior == "allow", f"{tool} should be allowed in sniff mode"


def test_sniff_mode_allows_safe_shell():
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=True))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "git status"},
        ToolPermissionContext(mode="sniff"),
        approval,
    )

    assert decision.behavior == "allow"


def test_sniff_mode_denies_mutating_shell():
    approval = ApprovalController(AutoApprovalSettings(execute_safe_cmds=True))
    decision = can_use_tool_in_mode(
        "run_shell",
        {"command": "python manage.py migrate"},
        ToolPermissionContext(mode="sniff"),
        approval,
    )

    assert decision.behavior == "deny"
