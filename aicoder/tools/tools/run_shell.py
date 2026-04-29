"""run_shell — Shell 命令执行工具"""
from ..spec import ToolSpec, ParamSpec

RUN_SHELL_SPEC = ToolSpec(
    name="run_shell",
    description="Execute a CLI command on the system. Use this to run tests, build, lint, or read command output.",
    parameters=[
        ParamSpec(name="command", required=True,
                  description="The CLI command to execute. Must be valid for the current OS.",
                  usage="pytest tests/ -v"),
        ParamSpec(name="requires_approval", required=True,
                  description='Whether user should confirm before execution. Use "true" for destructive commands, "false" for safe reads.',
                  usage="true"),
    ],
    instruction="Prefer safe, read-only commands when possible. Set requires_approval=true for commands that modify files, install packages, or access the network.",
)
