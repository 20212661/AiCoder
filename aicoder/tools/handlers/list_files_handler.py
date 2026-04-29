import os, subprocess, platform
from .base import ToolHandler
from ..result import ToolCall, ToolResult

MAX_FILES = 200
DEFAULT_IGNORE = {"node_modules", "__pycache__", ".git", "env", "venv", ".venv",
    "dist", "out", "build", "vendor", "target", ".next", ".nuxt",
    "tmp", "temp", "Pods", ".pytest_cache", ".mypy_cache"}

class ListFilesHandler(ToolHandler):
    name = "list_files"
    requires_approval = False

    def validate_params(self, tool_call):
        return "" if tool_call.get("path") else "Missing required parameter: path"

    def execute(self, tool_call, coder):
        rel_path = tool_call.get("path")
        recursive = tool_call.get("recursive", "false").lower() == "true"
        full_path = coder.abs_root_path(rel_path)
        if not os.path.exists(full_path):
            return ToolResult.fail(self.name, "Path does not exist: " + rel_path)
        if not os.path.isdir(full_path):
            return ToolResult.fail(self.name, "Not a directory: " + rel_path)
        patterns = self._read_gitignore(full_path)
        try:
            files = self._list_files(full_path, recursive, patterns)
        except Exception as e:
            return ToolResult.fail(self.name, "Listing failed: " + str(e) + ". Try run_shell with dir/ls instead.")
        if not files:
            fb = self._try_fallback(full_path)
            if fb:
                return ToolResult.ok(self.name, fb)
            return ToolResult.ok(self.name, "No visible files found in " + rel_path)
        files.sort(key=lambda x: (0 if x[0].endswith("/") else 1, x[0].lower()))
        did = len(files) >= MAX_FILES
        lines = ["Contents of " + rel_path + ":"]
        for name, size in files[:MAX_FILES]:
            if name.endswith("/"): lines.append("  " + name)
            else: lines.append("  " + name.ljust(50) + " " + self._fmt(size).rjust(8))
        out = "\n".join(lines)
        cnt = str(len(files))
        if did: out += "\n\n[Showing " + str(MAX_FILES) + " of " + cnt + "+ entries]"
        else: out += "\n\n(" + cnt + " entries total)"
        return ToolResult.ok(self.name, out)

    def _list_files(self, root, recursive, patterns):
        files = []
        root = os.path.abspath(root)
        if recursive:
            dirs = [root]
            while dirs and len(files) < MAX_FILES:
                d = dirs.pop(0)
                try: entries = sorted(os.listdir(d))
                except Exception: continue
                for entry in entries:
                    if len(files) >= MAX_FILES: break
                    ap = os.path.join(d, entry)
                    if entry.startswith(".") and not self._special(entry): continue
                    if entry in DEFAULT_IGNORE: continue
                    if self._ignored(os.path.relpath(ap, root), patterns): continue
                    try:
                        if os.path.isdir(ap):
                            files.append((os.path.relpath(ap, root) + "/", "0"))
                            dirs.append(ap)
                        elif os.path.isfile(ap):
                            files.append((os.path.relpath(ap, root), str(os.path.getsize(ap))))
                    except Exception:
                        files.append((os.path.relpath(ap, root) + " [LOCKED]", "0"))
        else:
            try: entries = sorted(os.listdir(root))
            except Exception: return files
            for entry in entries[:MAX_FILES]:
                ap = os.path.join(root, entry)
                if entry.startswith(".") and not self._special(entry): continue
                try:
                    if os.path.isdir(ap): files.append((entry + "/", "0"))
                    elif os.path.isfile(ap): files.append((entry, str(os.path.getsize(ap))))
                except Exception: files.append((entry + " [LOCKED]", "0"))
        return files

    def _try_fallback(self, full_path):
        """os.listdir 在 Windows 上可能返回空 — 用 dir/ls 回退"""
        try:
            if platform.system() == "Windows":
                r = subprocess.run(["cmd", "/c", "dir", "/b", full_path],
                                   capture_output=True, text=True, timeout=10)
            else:
                r = subprocess.run(["ls", "-1", full_path],
                                   capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                lines = [l for l in r.stdout.strip().splitlines()
                         if not l.startswith(".")][:MAX_FILES]
                if lines:
                    return "Contents (via shell):\n  " + "\n  ".join(lines)
        except Exception:
            pass
        return ""

    def _read_gitignore(self, dir_path):
        patterns = set()
        gp = os.path.join(dir_path, ".gitignore")
        if not os.path.isfile(gp): return patterns
        try:
            with open(gp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("!"): continue
                    patterns.add(line[:-1] if line.endswith("/") else line)
        except Exception: pass
        return patterns

    def _ignored(self, rel, patterns):
        return any(p in rel.replace("\\", "/").split("/") for p in patterns)

    @staticmethod
    def _special(name):
        return name in {".", "..", ".git", ".vscode", ".idea"}

    @staticmethod
    def _fmt(s):
        s = int(s)
        if s == 0: return "-"
        if s < 1024: return str(s) + "B"
        if s < 1048576: return str(round(s / 1024, 1)) + "K"
        return str(round(s / 1048576, 1)) + "M"
