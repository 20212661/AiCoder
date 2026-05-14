# LangChain Runtime 第一阶段可执行计划

## 1. 阶段目标

第一阶段目标是新增一个实验性 LangChain runtime 旁路，让 aiCoder 可以通过显式参数运行 LangChain Agent。

必须满足：

```text
默认行为不变；
现有 ToolExecutor 不拆；
现有 rpc_io.py 不改；
现有 workflow.py 不替换；
LangChain Tool 只包装，不直接执行危险操作。
```

推荐任务名：

```text
Add experimental LangChain runtime adapter
```

## 2. 需要改动的文件

新增：

```text
aicoder/langchain_runtime/__init__.py
aicoder/langchain_runtime/model.py
aicoder/langchain_runtime/schemas.py
aicoder/langchain_runtime/tools.py
aicoder/langchain_runtime/agent.py
aicoder/tests/test_langchain_runtime.py
```

修改：

```text
pyproject.toml
aicoder/main.py
aicoder/coders/base_coder.py
```

可选修改：

```text
aicoder/runners/langchain_agent_runner.py
```

如果当前 runner 架构接入成本较高，第一阶段可以先不新增 runner，直接在 `Coder.run()` 的入口处做最小分支。

## 3. 依赖修改

在 `pyproject.toml` 的 `dependencies` 中新增：

```toml
"langchain-litellm>=0.2.0",
```

注意：

- 项目已经有 `langgraph>=0.2.0` 和 `langchain-core>=0.3.0`
- 不要移除现有 `litellm`
- 不要替换现有 `llm.py`

## 4. 新增 model.py

路径：

```text
aicoder/langchain_runtime/model.py
```

建议实现：

```python
from __future__ import annotations

from langchain_litellm import ChatLiteLLM


def build_chat_model(model_name: str) -> ChatLiteLLM:
    return ChatLiteLLM(
        model=model_name,
        temperature=0,
    )
```

要求：

- 函数只负责构建 LangChain ChatModel
- 不要在这里做 API key 检查
- API key 检查继续使用当前 `main.py` 的逻辑

## 5. 新增 schemas.py

路径：

```text
aicoder/langchain_runtime/schemas.py
```

建议实现：

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    path: str = Field(description="File path to read")


class WriteFileArgs(BaseModel):
    path: str = Field(description="File path to write")
    content: str = Field(description="New file content")


class EditFileArgs(BaseModel):
    path: str = Field(description="File path to edit")
    old: str = Field(description="Text to replace")
    new: str = Field(description="Replacement text")


class SearchFilesArgs(BaseModel):
    path: str = Field(default=".", description="Directory to search")
    pattern: str = Field(description="Search pattern")


class RunShellArgs(BaseModel):
    command: str = Field(description="Shell command to run")
    timeout: str | None = Field(default=None, description="Optional timeout seconds")
```

注意：

- 参数名必须和现有 tool handler 期望尽量一致
- 如果现有 handler 使用的字段不是 `path` / `pattern`，以现有 handler 为准
- 不要在第一阶段加入 structured output schema，避免范围扩大

## 6. 新增 tools.py

路径：

```text
aicoder/langchain_runtime/tools.py
```

建议实现：

```python
from __future__ import annotations

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


def _run_existing_tool(coder: Any, name: str, params: dict[str, str]) -> str:
    result = coder.tool_executor.execute(ToolCall(name=name, params=params))
    if result.success:
        return result.output
    raise RuntimeError(result.error or f"Tool failed: {name}")


def build_langchain_tools(coder: Any) -> list[StructuredTool]:
    def read_file(path: str) -> str:
        return _run_existing_tool(coder, "read_file", {"path": path})

    def write_file(path: str, content: str) -> str:
        return _run_existing_tool(
            coder,
            "write_file",
            {
                "path": path,
                "content": content,
            },
        )

    def edit_file(path: str, old: str, new: str) -> str:
        return _run_existing_tool(
            coder,
            "edit_file",
            {
                "path": path,
                "old": old,
                "new": new,
            },
        )

    def search_files(pattern: str, path: str = ".") -> str:
        return _run_existing_tool(
            coder,
            "search_files",
            {
                "path": path,
                "pattern": pattern,
            },
        )

    def run_shell(command: str, timeout: str | None = None) -> str:
        params = {"command": command}
        if timeout is not None:
            params["timeout"] = timeout
        return _run_existing_tool(coder, "run_shell", params)

    return [
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
```

关键要求：

- 不允许直接使用 `open()` 读写文件
- 不允许直接调用 `subprocess`
- 不允许绕过 `coder.tool_executor.execute()`
- 工具失败时抛 `RuntimeError`，让 LangChain 能识别工具失败

## 7. 新增 agent.py

路径：

```text
aicoder/langchain_runtime/agent.py
```

建议实现：

```python
from __future__ import annotations

from typing import Any

from langchain.agents import create_agent

from .model import build_chat_model
from .tools import build_langchain_tools


SYSTEM_PROMPT = """
You are AiCoder, an AI pair programming agent.

You can inspect code, search files, edit files, and run commands.
All file, git, shell, and workspace operations must be performed through tools.
Do not claim that a tool succeeded unless the tool result confirms success.
If a tool call is rejected or blocked, explain the limitation and choose a safer alternative.
"""


def build_langchain_agent(coder: Any):
    model = build_chat_model(coder.main_model.name)
    tools = build_langchain_tools(coder)
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content or "")


def run_langchain_agent(coder: Any, user_message: str) -> str:
    agent = build_langchain_agent(coder)
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": user_message,
                }
            ]
        }
    )

    messages = result.get("messages", [])
    if not messages:
        return ""
    return _message_content(messages[-1])
```

注意：

- 不要在第一阶段加入 middleware
- 不要在第一阶段加入 checkpointer
- 不要在第一阶段加入 structured output
- `coder.main_model.name` 如果在当前代码中字段不同，以实际字段为准

## 8. 修改 main.py

路径：

```text
aicoder/main.py
```

在 parser 中新增参数：

```python
parser.add_argument(
    "--runtime",
    choices=["legacy", "langchain"],
    default="legacy",
    help="Agent runtime backend to use",
)
```

在 `coder = Coder.create(...)` 成功后设置：

```python
coder.runtime = args.runtime
```

注意：

- 默认值必须是 `legacy`
- 不要改变 `--serve` 的默认行为

## 9. 修改 Coder.run 接入分支

路径：

```text
aicoder/coders/base_coder.py
```

在 `Coder.run()` 的合适入口增加：

```python
if getattr(self, "runtime", "legacy") == "langchain":
    if not with_message:
        self.io.tool_warning("LangChain runtime currently requires --message mode.")
        return None
    from aicoder.langchain_runtime.agent import run_langchain_agent

    text = run_langchain_agent(self, with_message)
    self.io.print_assistant_output(text)
    return text
```

要求：

- 只影响 `runtime == "langchain"` 的路径
- legacy 路径保持原样
- 第一阶段允许 LangChain runtime 只支持 `--message`

## 10. 单测建议

新增：

```text
aicoder/tests/test_langchain_runtime.py
```

建议测试点：

1. `build_langchain_tools(coder)` 返回工具列表。
2. 工具列表包含 `read_file`、`write_file`、`edit_file`、`search_files`、`run_shell`。
3. 调用 wrapper 时会进入 `coder.tool_executor.execute()`。
4. `ToolResult.fail(...)` 会被转换成 `RuntimeError`。
5. `--runtime` 参数默认值是 `legacy`。

示例思路：

```python
from aicoder.langchain_runtime.tools import _run_existing_tool, build_langchain_tools
from aicoder.tools.result import ToolResult


class FakeExecutor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, tool_call):
        self.calls.append(tool_call)
        return self.result


class FakeCoder:
    def __init__(self, result):
        self.tool_executor = FakeExecutor(result)


def test_run_existing_tool_success_calls_executor():
    coder = FakeCoder(ToolResult.ok("read_file", "hello"))
    output = _run_existing_tool(coder, "read_file", {"path": "README.md"})

    assert output == "hello"
    assert coder.tool_executor.calls[0].name == "read_file"
    assert coder.tool_executor.calls[0].params == {"path": "README.md"}


def test_run_existing_tool_failure_raises():
    coder = FakeCoder(ToolResult.fail("read_file", "missing"))

    try:
        _run_existing_tool(coder, "read_file", {"path": "missing.md"})
    except RuntimeError as err:
        assert "missing" in str(err)
    else:
        raise AssertionError("Expected RuntimeError")
```

## 11. 验证命令

建议先跑：

```powershell
python -m pytest aicoder/tests/test_langchain_runtime.py
```

再跑核心回归：

```powershell
python -m pytest aicoder/tests/test_tool_executor.py aicoder/tests/test_graph_act.py aicoder/tests/test_rpc_io.py
```

如果项目使用已配置脚本，也可以跑：

```powershell
npm run test:run
```

注意：

- 如果依赖未安装导致 `langchain_litellm` import 失败，需要先安装项目依赖
- 不要因为网络问题修改业务代码绕过依赖

## 12. 完成标准

第一阶段完成时必须满足：

```text
1. 默认 legacy runtime 不变
2. --runtime langchain 参数存在
3. --runtime langchain --message 可以进入新 runtime
4. LangChain Tool 调用现有 ToolExecutor
5. 工具失败会传递为 RuntimeError
6. 不修改 rpc_io.py
7. 不拆 executor.py
8. 不替换 workflow.py
9. 新增单测通过
10. 关键旧测试通过
```

## 13. 禁止事项

第一阶段禁止：

```text
1. 禁止直接读写文件绕过 ToolExecutor
2. 禁止直接执行 subprocess 绕过 ToolExecutor
3. 禁止把默认 runtime 改成 langchain
4. 禁止修改 --serve 默认行为
5. 禁止引入 HumanInTheLoopMiddleware
6. 禁止引入 checkpointer
7. 禁止大规模重构 base_coder.py
8. 禁止删除或拆分 executor.py
9. 禁止替换 workflow.py
10. 禁止修改 TUI RPC 协议
```

