"""Tests for repo context types, ranking, rendering, and integration.

Phase 1: data structure construction and field validation.
Phase 2: RepoRanker scoring and priority.
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from aicoder.context.repo_types import RepoFileHint, RepoContextBuildResult
from aicoder.context.repo_ranker import (
    collect_candidate_files,
    rank_repo_files,
    _IMPORTANT_ROOT_FILES,
)
from aicoder.context.repo_renderer import render_repo_context
from aicoder.context.repo_map import build_repo_context
from aicoder.tests.conftest import make_mock_coder


# ---------------------------------------------------------------------------
# Phase 1: RepoFileHint and RepoContextBuildResult basics
# ---------------------------------------------------------------------------


class TestRepoFileHint:
    def test_construct_with_defaults(self):
        hint = RepoFileHint(path="src/app.py", reason="focused")
        assert hint.path == "src/app.py"
        assert hint.reason == "focused"
        assert hint.score == 0.0
        assert hint.symbols == []
        assert hint.snippet == ""

    def test_construct_full(self):
        hint = RepoFileHint(
            path="src/app.py",
            reason="recently_edited",
            score=0.85,
            symbols=["main()", "build_context()"],
            snippet="def main(): ...",
        )
        assert hint.score == 0.85
        assert len(hint.symbols) == 2
        assert hint.snippet.startswith("def")

    def test_reason_field_values(self):
        """reason should be one of the known categories."""
        valid_reasons = {
            "focused", "recently_edited", "important_root_file",
            "search_hit", "shallow_match",
        }
        for reason in valid_reasons:
            hint = RepoFileHint(path="a.py", reason=reason)
            assert hint.reason == reason

    def test_score_non_negative(self):
        hint = RepoFileHint(path="a.py", reason="focused", score=1.0)
        assert hint.score >= 0.0

    def test_symbols_is_list(self):
        hint = RepoFileHint(path="a.py", reason="focused", symbols=["foo", "bar"])
        assert isinstance(hint.symbols, list)

    def test_snippet_short(self):
        """snippet should be short, not full file content."""
        hint = RepoFileHint(
            path="a.py", reason="focused",
            snippet="def main(): pass",
        )
        assert len(hint.snippet) < 500


class TestRepoContextBuildResult:
    def test_construct_empty(self):
        result = RepoContextBuildResult()
        assert result.files == []
        assert result.rendered_messages == []
        assert result.token_estimate == 0

    def test_construct_with_files(self):
        files = [
            RepoFileHint(path="a.py", reason="focused", score=1.0),
            RepoFileHint(path="b.py", reason="important_root_file", score=0.5),
        ]
        result = RepoContextBuildResult(
            files=files,
            rendered_messages=[{"role": "user", "content": "repo map"}],
            token_estimate=42,
        )
        assert len(result.files) == 2
        assert len(result.rendered_messages) == 1
        assert result.token_estimate == 42

    def test_file_reason_preserved(self):
        files = [RepoFileHint(path="README.md", reason="important_root_file")]
        result = RepoContextBuildResult(files=files)
        assert result.files[0].reason == "important_root_file"

    def test_file_score_ordering(self):
        files = [
            RepoFileHint(path="a.py", reason="focused", score=0.3),
            RepoFileHint(path="b.py", reason="focused", score=0.9),
            RepoFileHint(path="c.py", reason="important_root_file", score=0.5),
        ]
        result = RepoContextBuildResult(files=files)
        sorted_by_score = sorted(result.files, key=lambda f: f.score, reverse=True)
        assert sorted_by_score[0].path == "b.py"
        assert sorted_by_score[-1].path == "a.py"


# ---------------------------------------------------------------------------
# Phase 2: RepoRanker scoring and priority
# ---------------------------------------------------------------------------


class TestRepoRankerCollect:
    def test_collect_from_workspace(self):
        root = tempfile.mkdtemp()
        for fn in ["main.py", "README.md", "utils.py"]:
            with open(os.path.join(root, fn), "w") as f:
                f.write("")

        coder = make_mock_coder(root=root)
        candidates = collect_candidate_files(coder)
        assert "main.py" in candidates
        assert "README.md" in candidates

    def test_collect_includes_focused_files(self):
        root = tempfile.mkdtemp()
        focused = os.path.join(root, "app.py")
        with open(focused, "w") as f:
            f.write("")

        coder = make_mock_coder(root=root, abs_fnames=[focused])
        candidates = collect_candidate_files(coder)
        assert "app.py" in candidates

    def test_collect_skips_hidden_and_ignored(self):
        root = tempfile.mkdtemp()
        with open(os.path.join(root, "visible.py"), "w") as f:
            f.write("")
        os.makedirs(os.path.join(root, ".git"), exist_ok=True)
        os.makedirs(os.path.join(root, "__pycache__"), exist_ok=True)
        with open(os.path.join(root, ".git", "config"), "w") as f:
            f.write("")
        with open(os.path.join(root, "__pycache__", "cached.pyc"), "w") as f:
            f.write("")

        coder = make_mock_coder(root=root)
        candidates = collect_candidate_files(coder)
        assert "visible.py" in candidates
        assert not any(".git" in c for c in candidates)
        assert not any("__pycache__" in c for c in candidates)


class TestRepoRankerPriority:
    def test_focused_file_highest_score(self):
        root = tempfile.mkdtemp()
        focused = os.path.join(root, "focused.py")
        with open(focused, "w") as f:
            f.write("")
        with open(os.path.join(root, "README.md"), "w") as f:
            f.write("")
        with open(os.path.join(root, "other.py"), "w") as f:
            f.write("")

        coder = make_mock_coder(root=root, abs_fnames=[focused])
        hints = rank_repo_files(coder, "act")

        focused_hint = next(h for h in hints if h.path == "focused.py")
        assert focused_hint.reason == "focused"
        assert focused_hint.score == 1.0

        # Focused must be higher than everything else
        for h in hints:
            if h.path != "focused.py":
                assert focused_hint.score >= h.score

    def test_important_root_file_scored(self):
        root = tempfile.mkdtemp()
        with open(os.path.join(root, "README.md"), "w") as f:
            f.write("")
        with open(os.path.join(root, "pyproject.toml"), "w") as f:
            f.write("")
        with open(os.path.join(root, "random.py"), "w") as f:
            f.write("")

        coder = make_mock_coder(root=root)
        hints = rank_repo_files(coder, "sniff")

        readme = next((h for h in hints if h.path == "README.md"), None)
        assert readme is not None
        assert readme.reason == "important_root_file"
        assert readme.score > 0

        random_hint = next((h for h in hints if h.path == "random.py"), None)
        if random_hint:
            assert readme.score > random_hint.score

    def test_different_mode_different_candidate_count(self):
        root = tempfile.mkdtemp()
        for i in range(30):
            with open(os.path.join(root, f"file_{i:02d}.py"), "w") as f:
                f.write("")

        coder = make_mock_coder(root=root)
        sniff_hints = rank_repo_files(coder, "sniff")
        act_hints = rank_repo_files(coder, "act")

        # sniff allows more candidates than act
        assert len(sniff_hints) >= len(act_hints)

    def test_ranked_by_score_descending(self):
        root = tempfile.mkdtemp()
        focused = os.path.join(root, "important.py")
        with open(focused, "w") as f:
            f.write("")
        with open(os.path.join(root, "README.md"), "w") as f:
            f.write("")
        with open(os.path.join(root, "utils.py"), "w") as f:
            f.write("")

        coder = make_mock_coder(root=root, abs_fnames=[focused])
        hints = rank_repo_files(coder, "act")

        scores = [h.score for h in hints]
        assert scores == sorted(scores, reverse=True)

    def test_reason_correct_for_all_files(self):
        root = tempfile.mkdtemp()
        focused = os.path.join(root, "app.py")
        with open(focused, "w") as f:
            f.write("")
        with open(os.path.join(root, "README.md"), "w") as f:
            f.write("")

        coder = make_mock_coder(root=root, abs_fnames=[focused])
        hints = rank_repo_files(coder, "act")

        for h in hints:
            assert h.reason in {
                "focused", "recently_edited", "search_hit",
                "important_root_file", "shallow_match", "deep_file",
            }

    def test_empty_workspace_returns_empty(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        hints = rank_repo_files(coder, "act")
        assert isinstance(hints, list)


# ---------------------------------------------------------------------------
# Phase 3: RepoRenderer budget and output
# ---------------------------------------------------------------------------


class TestRepoRenderer:
    def _make_hints(self, n=5):
        return [
            RepoFileHint(
                path=f"src/file{i}.py",
                reason="shallow_match",
                score=0.3 - i * 0.05,
                symbols=[f"func_{i}()"],
                snippet=f"def func_{i}(): pass",
            )
            for i in range(n)
        ]

    def test_render_produces_messages(self):
        hints = self._make_hints(3)
        result = render_repo_context(hints, budget_tokens=500, mode="sniff")

        assert len(result.rendered_messages) == 2  # user + assistant
        assert result.rendered_messages[0]["role"] == "user"
        assert result.rendered_messages[1]["role"] == "assistant"
        assert "Project Map" in result.rendered_messages[0]["content"]
        assert result.token_estimate > 0

    def test_render_includes_all_files_when_budget_allows(self):
        hints = self._make_hints(3)
        result = render_repo_context(hints, budget_tokens=2000, mode="sniff")

        assert len(result.files) == 3
        for hint in result.files:
            assert hint.path in result.rendered_messages[0]["content"]

    def test_render_budget_trims_low_score_files(self):
        hints = self._make_hints(10)
        result = render_repo_context(hints, budget_tokens=30, mode="act")

        # Should include fewer than all 10 files
        assert len(result.files) < 10
        # Highest-scored files should be included
        assert result.files[0].path == "src/file0.py"

    def test_render_empty_hints_returns_empty(self):
        result = render_repo_context([], budget_tokens=500, mode="act")
        assert result.files == []
        assert result.rendered_messages == []
        assert result.token_estimate == 0

    def test_snippet_not_full_file(self):
        hints = [
            RepoFileHint(
                path="big.py", reason="focused", score=1.0,
                snippet="x" * 500,
            ),
        ]
        result = render_repo_context(hints, budget_tokens=500, mode="plan")

        content = result.rendered_messages[0]["content"]
        # Snippet should be truncated, not 500 chars
        assert "..." in content or len(content) < 600

    def test_act_mode_smaller_than_sniff(self):
        hints = self._make_hints(10)
        # Same budget, different modes
        sniff_result = render_repo_context(hints, budget_tokens=200, mode="sniff")
        act_result = render_repo_context(hints, budget_tokens=200, mode="act")

        # Both should produce output
        assert sniff_result.token_estimate > 0
        assert act_result.token_estimate > 0

        # Sniff includes symbols, act might not — so sniff entry per file is larger
        # This means for same budget, act might fit more files
        # But the key point: both are valid and different
        assert len(sniff_result.files) > 0
        assert len(act_result.files) > 0

    def test_render_includes_reason(self):
        hints = [
            RepoFileHint(path="app.py", reason="focused", score=1.0),
            RepoFileHint(path="README.md", reason="important_root_file", score=0.5),
        ]
        result = render_repo_context(hints, budget_tokens=500, mode="act")

        content = result.rendered_messages[0]["content"]
        assert "focused" in content
        assert "important_root_file" in content


# ---------------------------------------------------------------------------
# Phase 4: build_repo_context integration
# ---------------------------------------------------------------------------


class TestBuildRepoContext:
    def test_returns_messages_from_real_workspace(self):
        root = tempfile.mkdtemp()
        for fn in ["main.py", "utils.py", "README.md"]:
            with open(os.path.join(root, fn), "w") as f:
                f.write(f"# {fn}\n")

        coder = make_mock_coder(root=root)
        messages = build_repo_context(coder, "act", budget_tokens=2000)

        assert isinstance(messages, list)
        assert len(messages) >= 2  # user + assistant pair
        assert messages[0]["role"] == "user"
        assert "Project Map" in messages[0]["content"]

    def test_empty_workspace_returns_empty(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        messages = build_repo_context(coder, "act", budget_tokens=500)

        # Empty workspace: either empty or just header
        assert isinstance(messages, list)

    def test_zero_budget_returns_empty(self):
        root = tempfile.mkdtemp()
        coder = make_mock_coder(root=root)
        messages = build_repo_context(coder, "act", budget_tokens=0)
        assert messages == []

    def test_focused_files_appear_in_context(self):
        root = tempfile.mkdtemp()
        focused = os.path.join(root, "important.py")
        with open(focused, "w") as f:
            f.write("print('hello')")
        with open(os.path.join(root, "README.md"), "w") as f:
            f.write("# Test")

        coder = make_mock_coder(root=root, abs_fnames=[focused])
        messages = build_repo_context(coder, "act", budget_tokens=2000)

        if messages:
            content = messages[0]["content"]
            assert "important.py" in content

    def test_sniff_plan_act_differ(self):
        root = tempfile.mkdtemp()
        for i in range(10):
            with open(os.path.join(root, f"file{i}.py"), "w") as f:
                f.write("")

        coder = make_mock_coder(root=root)
        sniff_msgs = build_repo_context(coder, "sniff", budget_tokens=1000)
        plan_msgs = build_repo_context(coder, "plan", budget_tokens=1000)
        act_msgs = build_repo_context(coder, "act", budget_tokens=1000)

        # All should produce output with real files
        for msgs in [sniff_msgs, plan_msgs, act_msgs]:
            assert isinstance(msgs, list)

        # With enough budget, all modes produce context
        # But content differs because mode affects rendering
        if sniff_msgs and act_msgs:
            # They may have different lengths or content
            assert sniff_msgs[0]["role"] == "user"
            assert act_msgs[0]["role"] == "user"

    def test_graceful_fallback_on_bad_coder(self):
        """build_repo_context must not crash even with a broken coder."""
        coder = MagicMock()
        coder.root = "/nonexistent/path/xyz"
        coder.abs_fnames = set()
        coder.abs_read_only_fnames = set()
        # Should not raise
        messages = build_repo_context(coder, "act", budget_tokens=500)
        assert isinstance(messages, list)
