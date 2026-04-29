# Cline 工具清单分析 & AiCoder 适配报告

> 分析 Cline 全部 27 个工具，评估哪些可引入 AiCoder
> 日期：2026-04-28

---

## 一、总览

Cline 共 27 个内置工具，分为 7 大类：

| 类别 | 数量 | 工具 |
|------|------|------|
| 文件操作 | 5 | read_file, write_to_file, replace_in_file, apply_patch, new_rule |
| 搜索探索 | 3 | search_files, list_files, list_code_definition_names |
| 命令执行 | 1 | execute_command |
| 浏览器网络 | 3 | browser_action, web_fetch, web_search |
| MCP | 3 | use_mcp_tool, access_mcp_resource, load_mcp_documentation |
| 对话交互 | 8 | ask_followup_question, attempt_completion, plan_mode_respond, act_mode_respond, new_task, todo, use_skill, generate_explanation |
| 子代理 | 4 | use_subagents, condense, summarize_task, report_bug |

---

## 二、AiCoder 适配评估

### 2.1 ✅ 已实现（4 个）

| Cline 工具 | AiCoder 对应 | 状态 |
|-----------|-------------|------|
| `read_file` | 手动 `/add` 加入聊天后自动读取 | 存在但非工具化 |
| `write_to_file` | `write_file` (WholeFileCoder + 新 ToolSpec) | ✅ |
| `replace_in_file` | `edit_file` (EditBlockCoder + 新 ToolSpec) | ✅ |
| `execute_command` | `run_shell` (新 ToolSpec + RunShellHandler) | ✅ 刚实施 |

### 2.2 🟢 高价值、建议引入（4 个）

| 工具 | 价值 | 实现难度 | 说明 |
|------|------|---------|------|
| **`search_files`** | 高 | 低 | 正则/Grep 搜索文件内容。AiCoder 已有 `grep-ast` 依赖，只需封装为 ToolSpec + Handler。LLM 在修改代码前可先搜索相关引用 |
| **`list_files`** | 高 | 低 | 列出目录结构。当前 `/ls` 只列聊天文件。让 LLM 能自主探索仓库结构 |
| **`list_code_definition_names`** | 高 | 中 | 列出代码定义（类/函数/方法）。AiCoder 已有 `tree-sitter` + AST 解析能力（repomap.py），可复用 |
| **`web_fetch`** | 中 | 低 | 抓取网页。可复用环境中的 `web_fetch` 工具。让 LLM 查文档、API 参考 |

### 2.3 🟡 中等价值、可选引入（3 个）

| 工具 | 价值 | 说明 |
|------|------|------|
| **`ask_followup_question`** | 中 | 工具执行中向用户提问。参数含 question + options(2-5选项)。可复用 `confirm_ask` |
| **`web_search`** | 中 | 网络搜索。依赖 Cline 自有搜索服务，AiCoder 可用 WebSearch 替代 |
| **`attempt_completion`** | 中 | 任务完成信号。让 LLM 主动标记任务完成并总结结果，代替当前"等用户看"的模式 |

### 2.4 🔴 不适用或暂不引入（16 个）

| 工具 | 原因 |
|------|------|
| `apply_patch` | V4A 格式，仅 GPT-5 模型支持 |
| `new_rule` | Cline 特有的规则系统 |
| `browser_action` | Puppeteer 依赖，当前环境无浏览器 |
| MCP × 3 | 需完整 MCP 集成，当前范围外 |
| `plan_mode_respond` | Cline Plan/Act 模式特有 |
| `act_mode_respond` | Cline Plan/Act 模式特有 |
| `new_task` | 子任务创建，复杂且当前模型支持有限 |
| `use_skill` | Cline Skill 系统，当前范围外 |
| `generate_explanation` | Cline 特有功能 |
| `use_subagents` | 多代理并行，过于复杂 |
| `condense` | Cline 内部上下文压缩 |
| `summarize_task` | Cline 内部任务摘要 |
| `report_bug` | Cline 内部错误报告 |
| `todo` | AiCoder 无对等概念（暂不需要） |

---

## 三、建议实施路线

### 本次建议实施（4 个高价值工具）

```
新增文件:
  aicoder/tools/tools/search_files.py        (~25 行)
  aicoder/tools/tools/list_files.py          (~20 行)
  aicoder/tools/tools/list_code_defs.py      (~25 行)
  aicoder/tools/tools/web_fetch.py           (~25 行)
  aicoder/tools/handlers/search_files_handler.py   (~50 行)
  aicoder/tools/handlers/list_files_handler.py     (~40 行)
  aicoder/tools/handlers/list_code_defs_handler.py (~60 行)
  aicoder/tools/handlers/web_fetch_handler.py      (~50 行)

修改文件:
  aicoder/coders/base_coder.py  _init_tool_system() 注册 4 个新工具  (+8 行)

合计: ~300 行新增代码
```

### 各工具设计要点

**`search_files` — 正则搜索文件内容**
- 参数: `path`(目录), `regex`(Rust 正则), `file_pattern`(glob, 可选)
- Handler: 内部调用 `grep_ast` 或 `ripgrep`，返回匹配行 + 行号
- 用途: LLM 在编辑前能先搜索"这个函数在哪里被调用"，避免盲改

**`list_files` — 列出目录结构**
- 参数: `path`(目录), `recursive`(bool)
- Handler: `os.walk` / `Path.rglob`，最多返回 200 个文件
- 用途: LLM 了解仓库结构，"有哪些 tests/ 文件？"

**`list_code_definition_names` — 列出代码定义**
- 参数: `path`(目录)
- Handler: 复用 `repomap.py` 的 `get_tags()` → 提取所有 `kind="def"` 的 Tag
- 用途: LLM 快速了解某目录有哪些类/函数/方法

**`web_fetch` — 抓取网页**
- 参数: `url`, `prompt`(可选的提取提示)
- Handler: 内部调用 `web_fetch` MCP 工具或 `urllib`
- 用途: LLM 查文档、"这个 API 的最新用法是什么？"

---

## 四、与现有 Cline 模式的对照

Cline 的 `search_files` Handler 内部实现：
```
SearchFilesToolHandler.execute()
  → spawnAsync("search_files", [directory, regex, filePattern])
  → 返回 { files: number, matches: Array<{path, startLine, content}> }
```

AiCoder 对应的实现路径更简单：
```
SearchFilesHandler.execute()
  → grep_ast / subprocess(["rg", "--line-number", regex, directory])
  → 返回 ToolResult.ok(output)
```

无需 native module 或 IPC，直接进程调用。

---

## 五、优先级建议

```
本次 (P0) ─ 立即可做，低风险高收益
  ├─ search_files     (LLM 能搜索后再编辑，减少盲改)
  ├─ list_files       (LLM 能自主探索仓库)
  └─ list_code_defs   (复用现有 tree-sitter 基础设施)

下次 (P1) ─ 需要额外环境支持
  └─ web_fetch        (需要有可用的 web fetch 服务)

可选 (P2) ─ 等工具系统稳定后
  ├─ ask_followup_question
  └─ attempt_completion
```
