from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool

from aicoder.tools.result import ToolCall

from .schemas import (
    EditFileArgs,
    ReadFileArgs,
    RunShellArgs,
    SearchFilesArgs,
    WriteFileArgs,
)

logger = logging.getLogger(__name__)


def _run_existing_tool(coder: Any, name: str, params: dict[str, str]) -> str:
    result = coder.tool_executor.execute(ToolCall(name=name, params=params))
    if result.success:
        return result.output
    raise RuntimeError(result.error or f"Tool failed: {name}")


def build_langchain_tools(coder: Any) -> list[StructuredTool]:
    def read_file(path: str) -> str:
        return _run_existing_tool(coder, "read_file", {"path": path})

    def write_file(path: str, content: str) -> str:
        return _run_existing_tool(coder, "write_file", {"path": path, "content": content})

    def edit_file(path: str, search: str, replace: str) -> str:
        return _run_existing_tool(
            coder, "edit_file", {"path": path, "search": search, "replace": replace}
        )

    def search_files(regex: str, path: str = ".", file_pattern: str = "") -> str:
        return _run_existing_tool(
            coder,
            "search_files",
            {"path": path, "regex": regex, "file_pattern": file_pattern},
        )

    def run_shell(command: str, timeout: int | None = None) -> str:
        params: dict[str, str] = {"command": command}
        if timeout is not None:
            params["timeout"] = str(timeout)
        return _run_existing_tool(coder, "run_shell", params)

    tools = [
        StructuredTool.from_function(
            func=read_file,
            name="read_file",
            description="Read a file from the current workspace through aiCoder safety checks.",
            args_schema=ReadFileArgs,
        ),
        StructuredTool.from_function(
            func=write_file,
            name="write_file",
            description="Write content to a file in the current workspace through aiCoder safety checks.",
            args_schema=WriteFileArgs,
        ),
        StructuredTool.from_function(
            func=edit_file,
            name="edit_file",
            description="Replace text in a file in the current workspace through aiCoder safety checks.",
            args_schema=EditFileArgs,
        ),
        StructuredTool.from_function(
            func=search_files,
            name="search_files",
            description="Search files in the current workspace through aiCoder safety checks.",
            args_schema=SearchFilesArgs,
        ),
        StructuredTool.from_function(
            func=run_shell,
            name="run_shell",
            description="Run a shell command through aiCoder safety checks.",
            args_schema=RunShellArgs,
        ),
    ]
    logger.info("build_langchain_tools: registered %s", [t.name for t in tools])
    return tools
