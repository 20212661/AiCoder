"""Tests for mode-specific context policy (v1.3 Phase 6 + Phase 7).

Validates that ContextPolicy produces real, measurable differences across
sniff/plan/act modes — not just in token budgets but in content strategy.
Phase 7: Validates focused_file_preference produces real behavioral differences.
"""
import os
import tempfile

import pytest

from aicoder.context.policies import (
    ContextPolicy,
    get_context_policy,
    get_context_budget_for_mode,
)
from aicoder.context.packer import (
    _trim_focused_files,
    _approx_token_count,
    _split_file_sections,
    _depth_trim_content,
    _breadth_trim_content,
    _balanced_trim_content,
)
from aicoder.context.repo_ranker import rank_repo_files
from aicoder.context.repo_renderer import render_repo_context
from aicoder.context.repo_types import RepoFileHint
from aicoder.tests.conftest import make_mock_coder


# ---------------------------------------------------------------------------
# ContextPolicy definition and lookup
# ---------------------------------------------------------------------------


class TestContextPolicyDefinition:
    def test_sniff_policy_fields(self):
        p = get_context_policy("sniff")
        assert p.repo_detail_level == "full"
        assert p.include_symbols is True
        assert p.include_snippets is True
        assert p.max_snippet_chars == 100
        assert p.focused_file_preference == "breadth"
        assert p.max_repo_candidates == 40

    def test_plan_policy_fields(self):
        p = get_context_policy("plan")
        assert p.repo_detail_level == "moderate"
        assert p.include_symbols is True
        assert p.include_snippets is True
        assert p.max_snippet_chars == 200
        assert p.focused_file_preference == "balanced"
        assert p.max_repo_candidates == 25

    def test_act_policy_fields(self):
        p = get_context_policy("act")
        assert p.repo_detail_level == "minimal"
        assert p.include_symbols is False
        assert p.include_snippets is False
        assert p.max_snippet_chars == 0
        assert p.focused_file_preference == "depth"
        assert p.max_repo_candidates == 15

    def test_unknown_mode_defaults_to_act(self):
        p = get_context_policy("nonexistent")
        act = get_context_policy("act")
        assert p.repo_detail_level == act.repo_detail_level

    def test_policy_is_frozen(self):
        p = get_context_policy("sniff")
        with pytest.raises(AttributeError):
            p.include_symbols = False  # type: ignore[misc]

    def test_mode_goal_property(self):
        assert "breadth" in get_context_policy("sniff").mode_goal
        assert "balanced" in get_context_policy("plan").mode_goal
        assert "minimal" in get_context_policy("act").mode_goal


# ---------------------------------------------------------------------------
# Budget vs Policy cross-checks
# ---------------------------------------------------------------------------


class TestBudgetPolicyCrossCheck:
    def test_sniff_has_largest_repo_budget_and_candidates(self):
        b = get_context_budget_for_mode("sniff")
        p = get_context_policy("sniff")
        plan_b = get_context_budget_for_mode("plan")
        act_b = get_context_budget_for_mode("act")
        assert b.repo_map_tokens > plan_b.repo_map_tokens
        assert b.repo_map_tokens > act_b.repo_map_tokens
        assert p.max_repo_candidates > get_context_policy("plan").max_repo_candidates

    def test_act_has_largest_focused_budget(self):
        act_b = get_context_budget_for_mode("act")
        sniff_b = get_context_budget_for_mode("sniff")
        plan_b = get_context_budget_for_mode("plan")
        assert act_b.focused_file_tokens > plan_b.focused_file_tokens
        assert act_b.focused_file_tokens > sniff_b.focused_file_tokens

    def test_plan_is_between_sniff_and_act_on_repo(self):
        sniff = get_context_budget_for_mode("sniff").repo_map_tokens
        plan = get_context_budget_for_mode("plan").repo_map_tokens
        act = get_context_budget_for_mode("act").repo_map_tokens
        assert sniff > plan > act

    def test_plan_is_between_act_and_sniff_on_focused(self):
        sniff = get_context_budget_for_mode("sniff").focused_file_tokens
        plan = get_context_budget_for_mode("plan").focused_file_tokens
        act = get_context_budget_for_mode("act").focused_file_tokens
        assert sniff < plan < act


# ---------------------------------------------------------------------------
# Policy affects ranker output
# ---------------------------------------------------------------------------


class TestPolicyAffectsRanker:
    def test_sniff_considers_more_candidates_than_act(self):
        root = tempfile.mkdtemp()
        for i in range(50):
            with open(os.path.join(root, f"file_{i:02d}.py"), "w") as f:
                f.write("")

        coder = make_mock_coder(root=root)
        sniff_hints = rank_repo_files(coder, "sniff")
        act_hints = rank_repo_files(coder, "act")

        # Policy caps: sniff=40, act=15
        assert len(sniff_hints) >= len(act_hints)
        assert len(sniff_hints) <= 40
        assert len(act_hints) <= 15

    def test_plan_candidates_between_sniff_and_act(self):
        root = tempfile.mkdtemp()
        for i in range(50):
            with open(os.path.join(root, f"f{i:02d}.py"), "w") as f:
                f.write("")

        coder = make_mock_coder(root=root)
        sniff = rank_repo_files(coder, "sniff")
        plan = rank_repo_files(coder, "plan")
        act = rank_repo_files(coder, "act")

        assert len(sniff) >= len(plan) >= len(act)


# ---------------------------------------------------------------------------
# Policy affects renderer output
# ---------------------------------------------------------------------------


class TestPolicyAffectsRenderer:
    def _make_hints(self, n=5):
        return [
            RepoFileHint(
                path=f"src/mod{i}.py",
                reason="shallow_match",
                score=0.5 - i * 0.05,
                symbols=[f"func_{i}()", f"Class{i}"],
                snippet=f"def func_{i}(): return {i}" * 10,
            )
            for i in range(n)
        ]

    def test_sniff_includes_symbols(self):
        hints = self._make_hints(3)
        result = render_repo_context(hints, budget_tokens=2000, mode="sniff")
        content = result.rendered_messages[0]["content"]
        assert "Contains:" in content

    def test_act_excludes_symbols(self):
        hints = self._make_hints(3)
        result = render_repo_context(hints, budget_tokens=2000, mode="act")
        content = result.rendered_messages[0]["content"]
        assert "Contains:" not in content

    def test_sniff_includes_short_snippets(self):
        hints = self._make_hints(3)
        result = render_repo_context(hints, budget_tokens=5000, mode="sniff")
        content = result.rendered_messages[0]["content"]
        assert "Snippet:" in content

    def test_plan_includes_longer_snippets_than_sniff(self):
        hints = self._make_hints(3)
        sniff_result = render_repo_context(hints, budget_tokens=5000, mode="sniff")
        plan_result = render_repo_context(hints, budget_tokens=5000, mode="plan")
        sniff_content = sniff_result.rendered_messages[0]["content"]
        plan_content = plan_result.rendered_messages[0]["content"]
        # Plan has max_snippet_chars=200, sniff has 100
        assert "Snippet:" in plan_content
        # Plan should have more content (longer snippets)
        assert len(plan_content) >= len(sniff_content)

    def test_act_excludes_snippets(self):
        hints = self._make_hints(3)
        result = render_repo_context(hints, budget_tokens=2000, mode="act")
        content = result.rendered_messages[0]["content"]
        assert "Snippet:" not in content

    def test_act_entry_is_compact(self):
        hints = self._make_hints(5)
        result = render_repo_context(hints, budget_tokens=2000, mode="act")
        content = result.rendered_messages[0]["content"]
        # Act mode: just "- path — reason" per file, no symbols/snippets
        for line in content.split("\n"):
            if line.startswith("- "):
                assert "—" in line  # has reason
                # No "Contains:" or "Snippet:" on following lines
        assert "Contains:" not in content
        assert "Snippet:" not in content


# ---------------------------------------------------------------------------
# Trace observability: pack_context includes policy info
# ---------------------------------------------------------------------------


class TestPolicyTraceObservability:
    def _make_coder_for_pack(self, root):
        from aicoder.tests.conftest import make_graph_coder
        coder = make_graph_coder(responses=["ok"], root=root)
        coder._first_message = False
        coder.gpt_prompts.files_content_prefix = ""
        coder.gpt_prompts.files_content_assistant_reply = "Ok."
        return coder

    def test_trace_includes_policy_detail_level(self):
        root = tempfile.mkdtemp()
        coder = self._make_coder_for_pack(root)
        from aicoder.context.packer import pack_context

        result = pack_context(coder, "hello", mode="sniff", runner_type="cot")
        trace = result._layer_trace
        assert trace.get("policy_detail_level") == "full"

    def test_trace_differs_between_modes(self):
        root = tempfile.mkdtemp()
        from aicoder.context.packer import pack_context

        traces = {}
        for mode in ("sniff", "plan", "act"):
            coder = self._make_coder_for_pack(root)
            result = pack_context(coder, "hello", mode=mode, runner_type="cot")
            traces[mode] = result._layer_trace

        # Detail levels differ
        assert traces["sniff"]["policy_detail_level"] == "full"
        assert traces["plan"]["policy_detail_level"] == "moderate"
        assert traces["act"]["policy_detail_level"] == "minimal"

        # Symbol/snippet flags differ
        assert traces["sniff"]["policy_include_symbols"] is True
        assert traces["act"]["policy_include_symbols"] is False
        assert traces["sniff"]["policy_include_snippets"] is True
        assert traces["act"]["policy_include_snippets"] is False

    def test_trace_shows_focused_preference(self):
        root = tempfile.mkdtemp()
        coder = self._make_coder_for_pack(root)
        from aicoder.context.packer import pack_context

        result = pack_context(coder, "hello", mode="act", runner_type="cot")
        assert result._layer_trace.get("policy_focused_pref") == "depth"


# ---------------------------------------------------------------------------
# End-to-end: mode differences visible in packed context
# ---------------------------------------------------------------------------


class TestModeDifferencesVisible:
    def test_sniff_repo_richer_than_act_with_symbols(self):
        """When hints have symbols/snippets, sniff renders richer output than act."""
        hints = [
            RepoFileHint(
                path=f"mod{i}.py",
                reason="shallow_match",
                score=0.5 - i * 0.02,
                symbols=[f"func_{i}()", f"Class{i}"],
                snippet=f"def func_{i}(): return {i}",
            )
            for i in range(15)
        ]

        sniff_result = render_repo_context(hints, budget_tokens=8000, mode="sniff")
        act_result = render_repo_context(hints, budget_tokens=8000, mode="act")

        sniff_content = sniff_result.rendered_messages[0]["content"]
        act_content = act_result.rendered_messages[0]["content"]

        # Sniff includes symbols, act does not
        assert "Contains:" in sniff_content
        assert "Contains:" not in act_content
        # Sniff content is larger because of symbol lines
        assert len(sniff_content) > len(act_content)


# ---------------------------------------------------------------------------
# focused_file_preference behavioral tests (Phase 7)
# ---------------------------------------------------------------------------


def _make_multi_file_content(n_files=5, chars_per_file=500):
    """Build content with multiple --- file sections."""
    header = "Working directory: /test\n\nFiles added to chat:\n\n"
    files = []
    for i in range(n_files):
        files.append(f"--- file{i}.py ---\n" + "x" * chars_per_file)
    return header + "\n\n".join(files)


def _make_multi_file_messages(n_files=5, chars_per_file=500):
    """Build mock chat file messages with multiple --- file sections."""
    content = _make_multi_file_content(n_files, chars_per_file)
    return [
        {"role": "user", "content": content},
        {"role": "assistant", "content": "Ok, I see the files."},
    ]


class TestFileSectionSplitting:
    def test_split_no_markers(self):
        content = "plain text without any markers"
        header, sections = _split_file_sections(content)
        assert header == content
        assert sections == []

    def test_split_with_markers(self):
        content = "Header\n\n--- file1.py ---\ncontent1\n\n--- file2.py ---\ncontent2"
        header, sections = _split_file_sections(content)
        assert "Header" in header
        assert len(sections) == 2
        assert "file1.py" in sections[0]
        assert "file2.py" in sections[1]


class TestDepthTrimContent:
    def test_drops_trailing_files(self):
        """Depth strategy should drop entire trailing file sections."""
        content = _make_multi_file_content(n_files=5, chars_per_file=200)
        # Budget that fits ~2 files
        result = _depth_trim_content(content, max_chars=800)
        # Should contain file0 and file1 but NOT file2+
        assert "file0.py" in result
        assert "file1.py" in result
        assert "file4.py" not in result

    def test_no_markers_falls_back(self):
        """Without --- markers, falls back to simple truncation."""
        content = "x" * 1000
        result = _depth_trim_content(content, max_chars=200)
        assert len(result) <= 200


class TestBreadthTrimContent:
    def test_keeps_all_files(self):
        """Breadth strategy should keep all file sections, just truncated."""
        content = _make_multi_file_content(n_files=5, chars_per_file=500)
        # Budget that doesn't fit all files fully
        result = _breadth_trim_content(content, max_chars=2000)
        # All files should be represented
        for i in range(5):
            assert f"file{i}.py" in result

    def test_no_markers_falls_back(self):
        content = "x" * 1000
        result = _breadth_trim_content(content, max_chars=200)
        assert len(result) <= 200


class TestBalancedTrimContent:
    def test_truncates_last_file(self):
        """Balanced strategy should keep full files, truncate the last one."""
        content = _make_multi_file_content(n_files=5, chars_per_file=200)
        # Budget that fits ~3 files fully
        result = _balanced_trim_content(content, max_chars=900)
        assert "file0.py" in result
        assert "file1.py" in result
        assert "file2.py" in result

    def test_no_markers_falls_back(self):
        content = "x" * 1000
        result = _balanced_trim_content(content, max_chars=200)
        assert len(result) <= 200


class TestFocusedFilePreferenceBehavior:
    def test_breadth_keeps_more_files_than_depth(self):
        """Given same budget and content, breadth should keep more file sections."""
        messages = _make_multi_file_messages(n_files=6, chars_per_file=400)
        budget_tokens = 800  # tight budget

        sniff_result = _trim_focused_files(messages, budget_tokens, mode="sniff")
        act_result = _trim_focused_files(messages, budget_tokens, mode="act")

        sniff_content = sniff_result[0]["content"]
        act_content = act_result[0]["content"]

        # Count file markers in each result
        sniff_file_count = sniff_content.count("--- file")
        act_file_count = act_content.count("--- file")

        # Breadth (sniff) should keep more file sections than depth (act)
        assert sniff_file_count >= act_file_count

    def test_depth_keeps_more_content_per_file_than_breadth(self):
        """Depth should keep more content per surviving file than breadth."""
        messages = _make_multi_file_messages(n_files=5, chars_per_file=300)
        budget_tokens = 800

        act_result = _trim_focused_files(messages, budget_tokens, mode="act")
        sniff_result = _trim_focused_files(messages, budget_tokens, mode="sniff")

        act_content = act_result[0]["content"]
        sniff_content = sniff_result[0]["content"]

        # Count how many 'x' chars survive in file0 content
        # Depth keeps file0 intact (or nearly so)
        # Breadth truncates all files equally
        act_file0_section = act_content.split("--- file0.py ---")[1].split("\n\n---")[0] if "--- file0.py ---" in act_content else ""
        sniff_file0_section = sniff_content.split("--- file0.py ---")[1].split("\n\n---")[0] if "--- file0.py ---" in sniff_content else ""

        # Depth should have more content per surviving file
        assert len(act_file0_section) >= len(sniff_file0_section)

    def test_preference_produces_different_output(self):
        """Breadth and depth should produce different content for same input."""
        messages = _make_multi_file_messages(n_files=4, chars_per_file=500)
        budget_tokens = 300  # tight enough to force trimming

        sniff_result = _trim_focused_files(messages, budget_tokens, mode="sniff")
        act_result = _trim_focused_files(messages, budget_tokens, mode="act")

        sniff_content = sniff_result[0]["content"]
        act_content = act_result[0]["content"]

        # They should be different (not just the same truncation)
        assert sniff_content != act_content

    def test_no_markers_all_modes_same(self):
        """Without --- markers, all modes should produce same-length output."""
        content = "Working directory: /test\n\nFiles added to chat:\n\n" + "y" * 2000
        messages = [
            {"role": "user", "content": content},
            {"role": "assistant", "content": "Ok."},
        ]
        budget = 200

        sniff = _trim_focused_files(messages, budget, mode="sniff")
        plan = _trim_focused_files(messages, budget, mode="plan")
        act = _trim_focused_files(messages, budget, mode="act")

        # All should have same content length (no sections to split)
        assert len(sniff[0]["content"]) == len(plan[0]["content"])
        assert len(plan[0]["content"]) == len(act[0]["content"])
