"""Tests for the centralized ModeConfig system (Phase 1)."""
import pytest

from aicoder.modes.config import (
    ACT_MODE,
    PLAN_MODE,
    SNIFF_MODE,
    ModeConfig,
    MemoryPolicy,
    get_mode_config,
    is_read_only_mode,
    ALL_TOOLS,
    FILE_EDIT_TOOLS,
    READ_ONLY_TOOLS,
)
from aicoder.mode_definitions import (
    get_mode_def,
    get_visible_tools,
    is_edit_allowed,
    get_shell_policy,
)
from aicoder.permission_modes import (
    can_use_tool_in_mode,
    get_visible_tool_specs,
    ToolPermissionContext,
)


# ---------------------------------------------------------------------------
# 1. Three modes exist
# ---------------------------------------------------------------------------

class TestModeExistence:
    def test_all_three_modes_exist(self):
        for name in ("sniff", "plan", "act"):
            cfg = get_mode_config(name)
            assert cfg.name == name

    def test_unknown_mode_defaults_to_act(self):
        cfg = get_mode_config("nonexistent")
        assert cfg.name == "act"

    def test_mode_configs_are_frozen(self):
        with pytest.raises(AttributeError):
            SNIFF_MODE.name = "other"


# ---------------------------------------------------------------------------
# 2. sniff / plan are read-only
# ---------------------------------------------------------------------------

class TestReadOnlyModes:
    @pytest.mark.parametrize("mode", ["sniff", "plan"])
    def test_sniff_and_plan_are_read_only(self, mode):
        assert is_read_only_mode(mode) is True

    @pytest.mark.parametrize("mode", ["sniff", "plan"])
    def test_edit_not_allowed(self, mode):
        assert is_edit_allowed(mode) is False

    @pytest.mark.parametrize("mode", ["sniff", "plan"])
    def test_shell_policy_is_readonly(self, mode):
        assert get_shell_policy(mode) == "readonly"

    @pytest.mark.parametrize("mode", ["sniff", "plan"])
    def test_edit_tools_not_visible(self, mode):
        assert not (FILE_EDIT_TOOLS & get_visible_tools(mode))


# ---------------------------------------------------------------------------
# 3. act is editable
# ---------------------------------------------------------------------------

class TestActMode:
    def test_act_is_editable(self):
        assert is_read_only_mode("act") is False

    def test_act_edit_allowed(self):
        assert is_edit_allowed("act") is True

    def test_act_has_all_tools(self):
        assert get_visible_tools("act") == ALL_TOOLS

    def test_act_shell_policy_is_safe(self):
        assert get_shell_policy("act") == "safe"


# ---------------------------------------------------------------------------
# 4. Memory policies exist and differ
# ---------------------------------------------------------------------------

class TestMemoryPolicies:
    def test_each_mode_has_memory_policy(self):
        for cfg in (SNIFF_MODE, PLAN_MODE, ACT_MODE):
            assert isinstance(cfg.memory_policy, MemoryPolicy)

    def test_memory_policies_are_not_all_identical(self):
        policies = {cfg.name: cfg.memory_policy for cfg in (SNIFF_MODE, PLAN_MODE, ACT_MODE)}
        # At least one field should differ between modes
        assert policies["sniff"] != policies["act"] or policies["plan"] != policies["act"]

    def test_sniff_has_larger_repo_map_than_act(self):
        assert SNIFF_MODE.memory_policy.repo_map_tokens > ACT_MODE.memory_policy.repo_map_tokens

    def test_sniff_enables_summary(self):
        assert SNIFF_MODE.memory_policy.enable_summary is True

    def test_act_disables_summary(self):
        assert ACT_MODE.memory_policy.enable_summary is False


# ---------------------------------------------------------------------------
# 5. permission_modes.py behavior consistent with new config
# ---------------------------------------------------------------------------

class TestPermissionModesConsistency:
    def test_plan_visible_tools_match_config(self):
        from aicoder.permission_modes import PLAN_MODE_VISIBLE_TOOLS
        assert PLAN_MODE_VISIBLE_TOOLS == PLAN_MODE.visible_tools

    @pytest.mark.parametrize("mode", ["sniff", "plan"])
    def test_read_only_modes_deny_file_edits(self, mode):
        from aicoder.approval import ApprovalController
        decision = can_use_tool_in_mode(
            "edit_file",
            {"path": "main.py"},
            ToolPermissionContext(mode=mode),
            ApprovalController(),
        )
        assert decision.behavior == "deny"

    @pytest.mark.parametrize("mode", ["sniff", "plan"])
    def test_read_only_modes_allow_read_tools(self, mode):
        from aicoder.approval import ApprovalController
        for tool in ["read_file", "search_files", "list_files", "list_code_defs"]:
            decision = can_use_tool_in_mode(
                tool,
                {},
                ToolPermissionContext(mode=mode),
                ApprovalController(),
            )
            assert decision.behavior == "allow", f"{tool} should be allowed in {mode}"

    def test_act_mode_allows_all_tools(self):
        """Act mode should at least not deny any tool by default."""
        from aicoder.approval import ApprovalController
        for tool in ["read_file", "edit_file", "write_file"]:
            decision = can_use_tool_in_mode(
                tool,
                {"path": "main.py"},
                ToolPermissionContext(mode="act"),
                ApprovalController(),
            )
            assert decision.behavior != "deny"


# ---------------------------------------------------------------------------
# 6. Legacy ModeDefinition backward compatibility
# ---------------------------------------------------------------------------

class TestLegacyCompat:
    def test_get_mode_def_returns_correct_fields(self):
        sniff_def = get_mode_def("sniff")
        assert sniff_def.name == "sniff"
        assert sniff_def.label == "SNIFF"
        assert sniff_def.editable is False

    def test_get_mode_def_defaults_to_act(self):
        act_def = get_mode_def("unknown")
        assert act_def.name == "act"

    def test_get_visible_tools_consistent(self):
        for mode in ("sniff", "plan", "act"):
            from_config = get_mode_config(mode).visible_tools
            from_legacy = get_visible_tools(mode)
            assert from_config == from_legacy
