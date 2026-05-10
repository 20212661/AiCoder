"""Tests for aicoder.sniffing.recon_summary."""
import os
import tempfile
from types import SimpleNamespace

from aicoder.sniffing.recon_summary import build_sniff_recon_summary


def _make_coder_with_tree(root: str):
    """Create a minimal coder-like object pointing at *root*."""
    coder = SimpleNamespace()
    coder.root = root
    return coder


def _make_repo(tmp: str):
    """Create a minimal repo structure inside *tmp*."""
    # Root dirs
    for d in ("src", "tests", "aicoder", "docs"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    # Config files
    for f in ("pyproject.toml", "package.json", "pytest.ini"):
        with open(os.path.join(tmp, f), "w") as fh:
            fh.write("")
    # Entry files
    with open(os.path.join(tmp, "main.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(tmp, "aicoder", "__main__.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(tmp, "aicoder", "commands.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(tmp, "aicoder", "state.py"), "w") as fh:
        fh.write("")
    # Test files
    with open(os.path.join(tmp, "tests", "test_main.py"), "w") as fh:
        fh.write("")
    # Legacy signal
    os.makedirs(os.path.join(tmp, "old_backup"), exist_ok=True)
    with open(os.path.join(tmp, "deprecated_utils.py"), "w") as fh:
        fh.write("")
    # Doc + code dual path
    with open(os.path.join(tmp, "README.md"), "w") as fh:
        fh.write("")
    with open(os.path.join(tmp, "docs", "guide.md"), "w") as fh:
        fh.write("")


# ── Basic structure tests ──


def test_summary_contains_overview():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "发酵区概况" in result


def test_summary_contains_entry_points():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "嗅探入口" in result


def test_summary_contains_artifact_signals():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "构石痕迹候选" in result


def test_summary_contains_blast_radius():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "扩散范围候选" in result


def test_summary_starts_with_header():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert result.startswith("SNIFF RECON SUMMARY:")


# ── Graceful degradation ──


def test_summary_empty_on_bad_root():
    coder = _make_coder_with_tree("/nonexistent/path/that/does/not/exist")
    result = build_sniff_recon_summary(coder)
    assert result == ""


def test_summary_empty_on_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        # Empty dir produces no recon signals — returns empty string
        assert result == ""


# ── Content details ──


def test_summary_detects_config_files():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "pyproject.toml" in result
        assert "package.json" in result


def test_summary_detects_test_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "tests" in result


def test_summary_detects_command_entries():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "commands" in result


def test_summary_detects_legacy_signals():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "deprecated" in result.lower() or "backup" in result.lower() or "old" in result.lower()


def test_summary_detects_blast_layers():
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        coder = _make_coder_with_tree(tmp)
        result = build_sniff_recon_summary(coder)
        assert "测试层" in result


# ── Mode isolation: summary is NOT generated for non-sniff contexts ──
# (The message_builder tests cover that summary only appears in sniff mode)
