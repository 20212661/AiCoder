"""run_shell Handler — Shell 命令执行，参考 Cline ExecuteCommandToolHandler + CommandOrchestrator"""
import shlex, subprocess, time, os, re
from .base import ToolHandler
from ..result import ToolCall, ToolResult

# ── 超时常量 ──
DEFAULT_TIMEOUT = 30
LONG_RUNNING_TIMEOUT = 300
BACKGROUND_TIMEOUT = 600  # 后台命令硬超时 10 分钟

# ── 输出限制 ──
MAX_OUTPUT_LINES = 500       # 返回 AI 的最大行数
MAX_OUTPUT_BYTES = 80 * 1024  # 返回 AI 的最大字节 80KB
SUMMARY_HEAD_TAIL = 50        # 截断时保留首尾各 50 行

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

# ── 危险命令模式 ──
DANGEROUS_PATTERNS = [
    (r'\brm\s+-rf\s+/', 'DESTRUCTIVE: rm -rf on root path'),
    (r'\brm\s+-rf\s+~', 'DESTRUCTIVE: rm -rf on home directory'),
    (r'\bdd\s+if=', 'DESTRUCTIVE: dd can overwrite disks'),
    (r'>\s*/dev/sd[a-z]', 'DESTRUCTIVE: writing to raw disk device'),
    (r'\bchmod\s+-R\s+777\s+/', 'DESTRUCTIVE: chmod 777 on root'),
    (r'\bgit\s+push\s+--force\b.*\bmain\b', 'DESTRUCTIVE: force push to main'),
    (r':\(\)\s*\{\s*:\|:&\s*\}\s*;', 'FORK BOMB detected'),
]


class RunShellHandler(ToolHandler):
    name = "run_shell"
    requires_approval = True

    def validate_params(self, tool_call: ToolCall) -> str:
        if not tool_call.get("command"):
            return "Missing required parameter: command"
        return ""

    def execute(self, tool_call: ToolCall, coder) -> ToolResult:
        command = tool_call.get("command")
        requires_approval = tool_call.get("requires_approval", "true").lower() == "true"

        # ── 命令清理 ──
        command = self._clean_command(command)

        # ── 安全检查 ──
        danger = self._check_dangerous(command)
        if danger and requires_approval:
            # 额外确认
            extra = coder.io.confirm_ask(
                f"[WARNING] {danger}\n  Command: {command[:200]}\n  Execute anyway?"
            )
            if not extra:
                return ToolResult.create_rejected(self.name)

        # ── 超时决策 ──
        timeout = LONG_RUNNING_TIMEOUT if self._is_long_running(command) else DEFAULT_TIMEOUT

        # ── 执行 ──
        start_time = time.time()
        try:
            result = subprocess.run(
                shlex.split(command),
                capture_output=True, text=True,
                cwd=coder.root, timeout=timeout,
            )
            elapsed = time.time() - start_time
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            return ToolResult.fail(
                self.name,
                f"Command timed out after {timeout}s "
                f"(ran {elapsed:.0f}s before timeout).\n"
                "For long-running commands, the tool supports up to 300s timeout. "
                "If the command is still needed, use run_shell with a sub-command or "
                "redirect output to a file."
            )
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

    # ── 内部方法 ──

    @staticmethod
    def _clean_command(command: str) -> str:
        """清理命令：去除首尾空白、统一换行"""
        cmd = command.strip()
        # 去除首尾反引号（LLM 有时会多包一层）
        if cmd.startswith("`") and cmd.endswith("`"):
            cmd = cmd[1:-1].strip()
        return cmd

    def _is_long_running(self, command: str) -> bool:
        """检测是否为长运行命令（构建/测试/安装等）"""
        for pattern in LONG_RUNNING_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    def _check_dangerous(self, command: str) -> str:
        """检查命令是否包含危险操作，返回警告信息或空字符串"""
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

        # 头部
        result_lines.append(f"--- First {len(head)} lines ---")
        result_lines.extend(head)

        # 省略标记
        if skipped > 0:
            result_lines.append(f"\n... ({skipped} lines omitted) ...")

        # 尾部
        if tail:
            result_lines.append(f"\n--- Last {len(tail)} lines ---")
            result_lines.extend(tail)

        return "\n".join(result_lines)
