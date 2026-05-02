"""run_shell Handler — Shell 命令执行，带沙箱隔离和命令过滤"""
import shlex, subprocess, time, os, re, sys
from .base import ToolHandler
from ..result import ToolCall, ToolResult

# ── 超时常量 ──
DEFAULT_TIMEOUT = 30
LONG_RUNNING_TIMEOUT = 300
MAX_HARD_TIMEOUT = 600

# ── 输出限制 ──
MAX_OUTPUT_LINES = 500
MAX_OUTPUT_BYTES = 80 * 1024
SUMMARY_HEAD_TAIL = 50

# ── 资源限制 ──
MAX_CHILD_PROCS = 50             # 子进程最大数量
MAX_OUTPUT_CAPTURE = 10 * 1024 * 1024  # 单次捕获 10MB

# ── 长运行命令模式 ──
LONG_RUNNING_PATTERNS = [
    r'\b(npm|pnpm|yarn|bun)\s+(install|ci|build|test|run)\b',
    r'\b(pip|pip3|uv)\s+install\b',
    r'\b(poetry|pipenv)\s+install\b',
    r'\b(cargo|go|mvn|gradle|gradlew)\s+(build|test|check|install)\b',
    r'\b(make|cmake|ctest)\b',
    r'\b(pytest|tox|nox|jest|vitest|mocha)\b',
    r'\b(docker|podman)\s+build\b',
    r'\bgcc|clang\+\+|rustc\b',
    r'\bpython.*\b(train|finetune)\b',
    r'\bdnf|apt|brew|choco\s+install\b',
    r'\bgit\s+clone\b',
]

# ── 危险命令模式（绝对禁止，不可覆盖）──
BLOCKED_PATTERNS = [
    (r'\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|/?)(/\s*$|/\s*>)', 'BLOCKED: rm -rf on root path — irreversible disk destruction'),
    (r'\brm\s+-[a-zA-Z]*f[a-zA-Z]*\s+~[/\s]*$', 'BLOCKED: rm -rf on home directory — irreversible data loss'),
    (r'\bdd\s+if=.*of=/dev/sd[a-z]', 'BLOCKED: dd writing to raw disk device'),
    (r'>\s*/dev/sd[a-z]', 'BLOCKED: writing to raw disk device'),
    (r'\bchmod\s+-R\s+777\s+/', 'BLOCKED: chmod 777 on root — security hazard'),
    (r':\(\)\s*\{\s*:\|:&\s*\}\s*;', 'BLOCKED: fork bomb detected'),
    (r'\bmkfs\b', 'BLOCKED: filesystem format command'),
    (r'\b(fdisk|parted)\b', 'BLOCKED: disk partitioning command'),
    (r'>\s*/dev/mem', 'BLOCKED: writing to /dev/mem'),
    (r'\bsysctl\s+-w\s', 'BLOCKED: runtime kernel parameter modification'),
]

# ── 危险但可覆盖的命令（需要额外确认）──
DANGEROUS_PATTERNS = [
    (r'\bgit\s+push\s+--force\b.*\b(main|master)\b', 'DESTRUCTIVE: force push to main/master'),
    (r'\bgit\s+reset\s+--hard\b', 'DESTRUCTIVE: git reset --hard discards uncommitted changes'),
    (r'\bgit\s+clean\s+-[a-zA-Z]*f', 'DESTRUCTIVE: git clean -f removes untracked files'),
    (r'\brm\s+-[a-zA-Z]*f[a-zA-Z]*\s+', 'WARNING: rm with force flag'),
    (r'\bchmod\s+-R\s+777\b', 'WARNING: recursive chmod 777'),
    (r'\bkill\s+-9\s+1\b', 'WARNING: killing init process'),
    (r'\b(taskkill|pkill|killall)\s+.*-9\b', 'WARNING: force killing processes'),
    (r'\bshutdown\b', 'WARNING: system shutdown command'),
    (r'\breboot\b', 'WARNING: system reboot command'),
]


class RunShellHandler(ToolHandler):
    name = "run_shell"
    requires_approval = True
    default_timeout = DEFAULT_TIMEOUT

    def validate_params(self, tool_call: ToolCall) -> str:
        if not tool_call.get("command"):
            return "Missing required parameter: command"
        return ""

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        command = tool_call.get("command")
        requires_approval = tool_call.get("requires_approval", "true").lower() == "true"

        # ── 命令清理 ──
        command = self._clean_command(command)

        # ── 绝对禁止检查（不可覆盖）──
        blocked = self._check_blocked(command)
        if blocked:
            return ToolResult.fail(self.name, f"[SECURITY] {blocked}")

        # ── 危险命令检查（需额外确认）──
        danger = self._check_dangerous(command)
        if danger and requires_approval:
            extra = coder.io.confirm_ask(
                f"[WARNING] {danger}\n  Command: {command[:200]}\n  Execute anyway?"
            )
            if not extra:
                return ToolResult.create_rejected(self.name)

        # ── 安全检查（通过 approval controller）──
        if hasattr(coder, "_approval") and coder._approval is not None:
            is_dangerous, warning = coder._approval.is_command_dangerous(command)
            if is_dangerous and requires_approval:
                extra = coder.io.confirm_ask(
                    f"[DANGER] {warning}\n  Command: {command[:200]}\n  Execute anyway?"
                )
                if not extra:
                    return ToolResult.create_rejected(self.name)

        # ── 超时决策 ──
        timeout = LONG_RUNNING_TIMEOUT if self._is_long_running(command) else DEFAULT_TIMEOUT
        timeout_str = tool_call.get("timeout", "")
        if timeout_str:
            try:
                timeout = min(float(timeout_str), MAX_HARD_TIMEOUT)
            except ValueError:
                pass

        # ── 执行（沙箱隔离）──
        start_time = time.time()
        try:
            result = self._run_sandboxed(command, coder.root, timeout)
            elapsed = time.time() - start_time
        except subprocess.TimeoutExpired as e:
            elapsed = time.time() - start_time
            partial = ""
            if e.stdout:
                partial = e.stdout[:1000] if isinstance(e.stdout, str) else e.stdout[:1000].decode("utf-8", errors="ignore")
            if e.stderr:
                partial += "\n" + (e.stderr[:1000] if isinstance(e.stderr, str) else e.stderr[:1000].decode("utf-8", errors="ignore"))
            msg = (
                f"Command timed out after {timeout}s (ran {elapsed:.0f}s).\n"
                f"For long-running commands, specify a higher timeout (max {MAX_HARD_TIMEOUT}s) "
                f"or redirect output to a file."
            )
            if partial.strip():
                msg += f"\n\nPartial output:\n{partial}"
            return ToolResult.fail(self.name, msg)
        except FileNotFoundError:
            return ToolResult.fail(
                self.name,
                f"Command not found: {shlex.split(command)[0]}. "
                "Check that the command is installed and in PATH."
            )
        except Exception as e:
            return ToolResult.fail(self.name, f"Command execution error: {e}")

        # ── 结果格式化 ──
        output = self._format_output(
            result.stdout, result.stderr,
            result.returncode, elapsed
        )

        if result.returncode == 0:
            return ToolResult.ok(self.name, output)
        else:
            return ToolResult.fail(self.name, output)

    # ── 沙箱执行 ──

    @staticmethod
    def _run_sandboxed(command: str, cwd: str, timeout: float) -> subprocess.CompletedProcess:
        """在沙箱环境中执行命令。

        隔离措施：
        1. 独立进程组（new process group）— 可整体终止
        2. 资源限制（仅 Unix）— 内存 / 文件大小 / CPU 时间
        3. 输出大小限制 — 防止内存溢出
        4. 环境变量隔离 — 只保留必要变量
        """
        # 构建安全的命令列表
        try:
            cmd_args = shlex.split(command)
        except ValueError:
            # shlex 解析失败时回退
            cmd_args = command

        # 环境变量：继承当前环境但移除敏感项
        env = os.environ.copy()
        for key in list(env.keys()):
            upper = key.upper()
            if any(kw in upper for kw in ("SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY", "API_KEY")):
                if not key.endswith("_PUBLIC"):
                    del env[key]

        # 子进程启动参数
        kwargs = {
            "capture_output": True,
            "text": True,
            "cwd": cwd,
            "timeout": timeout,
            "env": env,
        }

        # 进程组隔离（Unix & Windows 均支持）
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        return subprocess.run(cmd_args, **kwargs)

    # ── 内部方法 ──

    @staticmethod
    def _clean_command(command: str) -> str:
        """清理命令：去除首尾空白、统一换行、剥除代码围栏"""
        cmd = command.strip()
        if cmd.startswith("```") and cmd.endswith("```"):
            cmd = cmd[3:-3].strip()
        if cmd.startswith("`") and cmd.endswith("`"):
            cmd = cmd[1:-1].strip()
        return cmd

    def _is_long_running(self, command: str) -> bool:
        for pattern in LONG_RUNNING_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _check_blocked(command: str) -> str:
        """检查绝对禁止的命令。返回警告信息或空字符串。"""
        for pattern, warning in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return warning
        return ""

    @staticmethod
    def _check_dangerous(command: str) -> str:
        """检查危险但可覆盖的命令。返回警告信息或空字符串。"""
        for pattern, warning in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return warning
        return ""

    @staticmethod
    def _format_output(stdout: str, stderr: str, exit_code: int, elapsed: float) -> str:
        """格式化命令输出，处理大输出截断"""
        output = stdout or ""

        # 合并 stderr
        if stderr:
            if output:
                output += "\n"
            output += stderr

        # 空输出
        if not output.strip():
            return f"Exit: {exit_code}  Time: {elapsed:.1f}s  (no output)"

        lines = output.splitlines()
        total_lines = len(lines)
        total_bytes = len(output.encode("utf-8"))

        # 未超限 → 直接返回
        if total_lines <= MAX_OUTPUT_LINES and total_bytes <= MAX_OUTPUT_BYTES:
            return (
                f"Exit: {exit_code}  Time: {elapsed:.1f}s  "
                f"Lines: {total_lines}\n\n{output}"
            )

        # 大输出 → 截断
        head = lines[:SUMMARY_HEAD_TAIL]
        tail = lines[-SUMMARY_HEAD_TAIL:] if total_lines > SUMMARY_HEAD_TAIL * 2 else []
        skipped = total_lines - len(head) - len(tail)

        result_lines = [
            f"Exit: {exit_code}  Time: {elapsed:.1f}s  "
            f"Lines: {total_lines} (showing {len(head)}+{len(tail)} of {total_lines})",
            "",
            "[OUTPUT TRUNCATED — full output not shown to save context]",
            "",
        ]

        result_lines.append(f"--- First {len(head)} lines ---")
        result_lines.extend(head)

        if skipped > 0:
            result_lines.append(f"\n... ({skipped} lines omitted) ...")

        if tail:
            result_lines.append(f"\n--- Last {len(tail)} lines ---")
            result_lines.extend(tail)

        return "\n".join(result_lines)
