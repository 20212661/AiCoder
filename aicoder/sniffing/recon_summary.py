# -*- coding: utf-8 -*-
"""Programmatic recon summary generator for sniff mode.

Produces a structured scaffold (发酵区概况 / 嗅探入口 / 构石痕迹 / 扩散范围候选)
from read-only repository information.  The summary is a *scaffold* for the LLM,
not a replacement for its analysis.
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..coders.base_coder import Coder

# ── Heuristic constants ──────────────────────────────────────────────

_TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "specs"}
_CONFIG_FILE_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "package.json", "tsconfig.json", "Cargo.toml", "go.mod", "Makefile",
    "docker-compose.yml", "docker-compose.yaml", ".env.example",
    "config.yaml", "config.yml", "config.json", "config.toml",
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".prettierrc",
    "pytest.ini", "conftest.py", "vite.config.ts", "next.config.js",
}
_ENTRY_FILE_PATTERNS = {
    "main.py", "app.py", "__main__.py", "index.ts", "index.tsx",
    "index.js", "index.jsx", "cli.py", "server.py", "manage.py",
    "run.py", "start.py", "entry.py", "app.ts", "app.tsx",
}
_LEGACY_SIGNALS = {"old", "backup", "copy", "tmp", "bak", "deprecated", "legacy", "orig"}

# Layer directory / file patterns for blast-radius estimation
_LAYER_PATTERNS = {
    "命令层": ["commands", "command", "cmd", "cli"],
    "状态层": ["state", "store", "stores", "model", "models", "reducer", "reducers"],
    "RPC 层": ["rpc", "api", "server", "routes"],
    "TUI 层": ["tui", "components", "ui", "views", "pages", "app"],
    "测试层": ["tests", "test", "__tests__", "spec", "specs"],
}


# ── Public entry point ───────────────────────────────────────────────

def build_sniff_recon_summary(coder: "Coder") -> str:
    """Build a read-only recon summary for sniff mode.

    Returns an empty string on any failure (graceful degradation).
    """
    try:
        root = coder.root
        if not root or not os.path.isdir(root):
            return ""

        tree = _parse_file_tree(root)
        sections: list[str] = []

        overview = _build_overview(tree)
        if overview:
            sections.append("发酵区概况:\n" + overview)

        entries = _build_entry_points(tree)
        if entries:
            sections.append("嗅探入口:\n" + entries)

        artifacts = _build_artifact_signals(tree)
        if artifacts:
            sections.append("构石痕迹候选:\n" + artifacts)

        blast = _build_blast_radius(tree)
        if blast:
            sections.append("扩散范围候选:\n" + blast)

        if not sections:
            return ""

        return "SNIFF RECON SUMMARY:\n\n" + "\n\n".join(sections) + "\n"
    except Exception:
        return ""


# ── Internal helpers ─────────────────────────────────────────────────

class _TreeInfo:
    """Lightweight parsed view of the repo file tree."""

    def __init__(self, root: str):
        self.root = root
        self.dirs: list[str] = []
        self.files: list[str] = []
        self.test_dirs: list[str] = []
        self.config_files: list[str] = []
        self.entry_files: list[str] = []
        self.legacy_signals: list[str] = []
        self._scan(root, "")

    def _scan(self, abs_dir: str, rel_base: str):
        try:
            entries = sorted(os.listdir(abs_dir))
        except (PermissionError, OSError):
            return

        for entry in entries:
            abs_path = os.path.join(abs_dir, entry)
            rel_path = (rel_base + "/" + entry) if rel_base else entry

            if os.path.isdir(abs_path):
                if entry in {"node_modules", "__pycache__", ".git", ".venv",
                             "venv", "dist", "build", ".next", ".turbo", "target",
                             ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache"}:
                    continue
                self.dirs.append(rel_path)
                name_lower = entry.lower()
                if name_lower in _TEST_DIR_NAMES:
                    self.test_dirs.append(rel_path)
                if any(s in name_lower for s in _LEGACY_SIGNALS):
                    self.legacy_signals.append(rel_path + "/")
                self._scan(abs_path, rel_path)
            elif os.path.isfile(abs_path):
                self.files.append(rel_path)
                if entry in _CONFIG_FILE_NAMES:
                    self.config_files.append(rel_path)
                if entry in _ENTRY_FILE_PATTERNS:
                    self.entry_files.append(rel_path)
                name_lower = entry.lower()
                if any(s in name_lower for s in _LEGACY_SIGNALS):
                    self.legacy_signals.append(rel_path)


def _parse_file_tree(root: str) -> _TreeInfo:
    return _TreeInfo(root)


def _build_overview(tree: _TreeInfo) -> str:
    lines: list[str] = []

    # Root-level key directories (first-level only)
    root_dirs = [d for d in tree.dirs if "/" not in d]
    if root_dirs:
        lines.append("- 根目录关键结构: " + ", ".join(root_dirs[:15]))

    # Test directories
    if tree.test_dirs:
        lines.append("- 测试目录: " + ", ".join(tree.test_dirs[:8]))

    # Config files
    if tree.config_files:
        lines.append("- 配置文件候选: " + ", ".join(tree.config_files[:12]))

    return "\n".join(lines)


def _build_entry_points(tree: _TreeInfo) -> str:
    lines: list[str] = []

    # Main entry files
    if tree.entry_files:
        lines.append("- 主入口文件候选: " + ", ".join(tree.entry_files[:10]))

    # Command entry candidates: files named command* or cmd*
    cmd_entries = [
        f for f in tree.files
        if any(f.lower().endswith(s) for s in ("command.py", "commands.py", "cmd.py", "cli.py", "cli.ts", "cli.js"))
    ]
    if cmd_entries:
        lines.append("- 命令入口候选: " + ", ".join(cmd_entries[:8]))

    # Workflow / state entry candidates
    state_entries = [
        f for f in tree.files
        if any(kw in f.lower() for kw in ("store", "state", "workflow", "graph", "agent", "runtime"))
    ]
    if state_entries:
        lines.append("- 工作流/状态入口候选: " + ", ".join(state_entries[:8]))

    return "\n".join(lines)


def _build_artifact_signals(tree: _TreeInfo) -> str:
    lines: list[str] = []

    # Legacy / old / backup signals
    if tree.legacy_signals:
        lines.append("- 历史残留/备份信号: " + ", ".join(tree.legacy_signals[:10]))

    # Duplicate entry file names (same basename in different directories)
    from collections import Counter
    basenames = [os.path.basename(f) for f in tree.entry_files]
    dup_basenames = [name for name, cnt in Counter(basenames).items() if cnt > 1]
    if dup_basenames:
        dups = []
        for name in dup_basenames:
            paths = [f for f in tree.entry_files if os.path.basename(f) == name]
            dups.append(name + " (" + ", ".join(paths) + ")")
        lines.append("- 重复入口文件: " + "; ".join(dups[:5]))

    # Doc vs implementation dual path: .md files that share name with code files
    md_files = {os.path.splitext(f)[0] for f in tree.files if f.endswith(".md")}
    code_files = {
        os.path.splitext(f)[0]
        for f in tree.files
        if f.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))
    }
    dual_paths = sorted(md_files & code_files)[:8]
    if dual_paths:
        lines.append("- 文档与实现双路径信号: " + ", ".join(dual_paths))

    return "\n".join(lines)


def _build_blast_radius(tree: _TreeInfo) -> str:
    lines: list[str] = []

    for layer_name, patterns in _LAYER_PATTERNS.items():
        matches = [
            d for d in tree.dirs
            if any(p in d.lower().split("/") for p in patterns)
        ]
        if matches:
            lines.append("- " + layer_name + ": " + ", ".join(matches[:5]))

    return "\n".join(lines)
