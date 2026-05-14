# 交付给 GLM 的第一阶段可执行提示词

你是一个代码实现 Agent。请在当前 aiCoder 项目中完成第一阶段任务：新增实验性 LangChain runtime adapter。

## 必读文档

请先阅读并遵守以下两个文档：

```text
docs/langchain-runtime-migration-overall-plan.md
docs/langchain-runtime-phase-1-execution-plan.md
```

## 任务目标

新增一条可显式启用的 LangChain runtime 旁路，但不改变默认行为。

最终应该支持：

```powershell
aicoder --runtime langchain --message "hello"
```

默认命令仍然走旧 runtime：

```powershell
aicoder --message "hello"
```

## 必须完成的改动

1. 修改 `pyproject.toml`

   在 dependencies 中新增：

   ```toml
   "langchain-litellm>=0.2.0",
   ```

   不要删除现有 `litellm`、`langchain-core`、`langgraph` 依赖。

2. 新增目录和文件：

   ```text
   aicoder/langchain_runtime/__init__.py
   aicoder/langchain_runtime/model.py
   aicoder/langchain_runtime/schemas.py
   aicoder/langchain_runtime/tools.py
   aicoder/langchain_runtime/agent.py
   ```

3. `model.py`

   实现 `build_chat_model(model_name: str)`，使用 `langchain_litellm.ChatLiteLLM`。

4. `schemas.py`

   为以下工具建立 Pydantic args schema：

   ```text
   read_file
   write_file
   edit_file
   search_files
   run_shell
   ```

   字段名要和现有 tool handler 兼容。如果发现现有 handler 的字段名和文档示例不同，以现有代码为准。

5. `tools.py`

   实现：

   ```python
   def _run_existing_tool(coder, name: str, params: dict[str, str]) -> str:
       ...

   def build_langchain_tools(coder) -> list:
       ...
   ```

   关键要求：

   ```text
   所有真实工具执行必须调用 coder.tool_executor.execute(ToolCall(...))
   不允许直接 open/read/write 文件
   不允许直接 subprocess 执行命令
   ToolResult.success 为 False 时必须抛 RuntimeError
   ```

6. `agent.py`

   实现：

   ```python
   def build_langchain_agent(coder):
       ...

   def run_langchain_agent(coder, user_message: str) -> str:
       ...
   ```

   使用 `langchain.agents.create_agent`。

   system prompt 需要强调：

   ```text
   所有文件、Git、Shell、workspace 操作必须通过工具完成。
   不要声称工具成功，除非工具结果确认成功。
   工具被拒绝或阻止时，解释限制并选择更安全的替代方案。
   ```

7. 修改 `aicoder/main.py`

   增加 CLI 参数：

   ```python
   parser.add_argument(
       "--runtime",
       choices=["legacy", "langchain"],
       default="legacy",
       help="Agent runtime backend to use",
   )
   ```

   在 `Coder.create(...)` 成功后设置：

   ```python
   coder.runtime = args.runtime
   ```

8. 修改 `aicoder/coders/base_coder.py`

   在 `Coder.run()` 的合适入口增加 langchain 分支。

   第一阶段允许 LangChain runtime 只支持 `--message` 模式：

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

   请根据实际 `Coder.run()` 结构选择最小侵入位置。

9. 新增测试：

   ```text
   aicoder/tests/test_langchain_runtime.py
   ```

   至少覆盖：

   ```text
   build_langchain_tools(coder) 返回工具列表
   工具名包含 read_file/write_file/edit_file/search_files/run_shell
   _run_existing_tool 成功时调用 coder.tool_executor.execute()
   _run_existing_tool 失败时抛 RuntimeError
   main.py parser 的 --runtime 默认值是 legacy
   ```

## 严格禁止

本阶段禁止做以下事情：

```text
禁止修改 rpc_io.py
禁止替换 workflow.py
禁止拆分 executor.py
禁止默认启用 langchain runtime
禁止修改 --serve 默认行为
禁止接入 middleware
禁止接入 interrupt
禁止接入 checkpointer
禁止直接读写文件绕过 ToolExecutor
禁止直接运行 subprocess 绕过 ToolExecutor
禁止大规模重构 Coder
```

## 验证要求

请至少运行：

```powershell
python -m pytest aicoder/tests/test_langchain_runtime.py
```

如果环境允许，再运行：

```powershell
python -m pytest aicoder/tests/test_tool_executor.py aicoder/tests/test_graph_act.py aicoder/tests/test_rpc_io.py
```

如果项目依赖需要安装但网络不可用，请不要绕过业务代码，请在最终说明中明确记录。

## 交付格式

完成后请汇报：

```text
1. 修改了哪些文件
2. 新增了哪些文件
3. 如何启用新 runtime
4. 运行了哪些测试
5. 是否有未完成项或环境阻塞
```

## 最终判断标准

这次任务完成后，项目应该具备：

```text
legacy runtime 默认稳定可用；
langchain runtime 可显式启用；
LangChain Tool 只作为现有 ToolExecutor 的适配层；
没有破坏 TUI/RPC、workflow.py、executor.py 的现有路径。
```

