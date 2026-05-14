# aiCoder v1.3 实现级任务拆解
版本：v1.3
主题：Repo Context 升级
目标读者：执行型编码 Agent（如 GLM）
执行要求：强约束、按阶段提交、每阶段必须可运行、可测试、可回退

---

## 0. 本版目标

v1.3 只做 4 件事：

1. 引入真正可用的 `repo context / project map`
2. 让 `focused_file_tokens` 真正落地
3. 细化 `sniff / plan / act` 三模式的 context policy
4. 让 `ContextPacker` 从“能工作”升级到“更会选上下文”

---

## 1. 强约束

### 1.1 必须遵守
1. 不允许移除 LangGraph 主链
2. 不允许破坏 v1.2.3 已通过的 FC / CoT / Event / History / Condensation
3. 不允许重写 `ContextPacker` 主骨架，只能增强
4. 不允许删掉现有 `build_repo_context()` 接口
5. repo context 必须受 token budget 约束
6. 不允许把整个仓库全文直接塞给模型
7. 模式差异必须通过 policy 和 budget 落地，不能只写 prompt
8. 每个阶段都必须补测试
9. 必须保留调试能力，新的 repo context 也要可 trace / dump

### 1.2 暂时禁止
1. 禁止完整迁移 Aider 全套实现
2. 禁止引入 tree-sitter 大规模语言适配重构
3. 禁止做数据库持久化
4. 禁止做 subagent 大改
5. 禁止改 TUI / RPC 大协议

### 1.3 代码风格要求
1. repo context 构建必须模块化
2. ranking / rendering / budgeting / selection 不能写成一个大函数
3. 所有 mode-specific policy 必须集中管理
4. 新增数据结构优先 dataclass / TypedDict
5. 所有预算逻辑必须能被测试和 trace

---

## 2. 完成定义

当 v1.3 完成时，系统必须满足：

1. `aicoder/context/repo_map.py` 不再只是空壳
2. `sniff / plan / act` 三模式的 repo context 大小和内容显著不同
3. `focused_file_tokens` 在 `ContextPacker` 中真实生效
4. repo context 会优先选择“相关文件 / 重要文件 / 最近文件”，而不是均匀塞满
5. repo context 可被 trace / dump
6. 长上下文下，repo context 不会挤爆 history / current messages
7. 现有测试不回归
8. 新增 repo-context 相关测试通过

---

## 3. 总体设计方向

本版重点借鉴 Aider，但只借最适合当前项目的 4 个思想：

1. 项目图谱不是全文，是压缩摘要
2. 按组件分配预算
3. 显式区分 full file context 和 repo map context
4. 模式不同，项目图谱粒度不同

---

## 4. 新增/修改模块规划

### 4.1 新增文件

- `aicoder/context/repo_types.py`
- `aicoder/context/repo_ranker.py`
- `aicoder/context/repo_renderer.py`
- `aicoder/tests/test_repo_map.py`
- `aicoder/tests/test_repo_context_budget.py`
- `aicoder/tests/test_mode_context_policy.py`

### 4.2 重点修改文件

- `aicoder/context/repo_map.py`
- `aicoder/context/policies.py`
- `aicoder/context/packer.py`
- `aicoder/debug/context_trace.py`
- `aicoder/debug/dump_helpers.py`
- 如有必要：
  - `aicoder/modes/config.py`
  - `aicoder/coders/message_builder.py`

---

## 5. 分阶段实施

---

# 阶段 1：定义 Repo Context 数据结构

## 5.1 目标
先把 repo context 从“字符串拼接”升级成有结构的数据。

## 5.2 要做的事

### 新建 `aicoder/context/repo_types.py`
建议定义：

```python
from dataclasses import dataclass, field

@dataclass
class RepoFileHint:
    path: str
    reason: str
    score: float = 0.0
    symbols: list[str] = field(default_factory=list)
    snippet: str = ""

@dataclass
class RepoContextBuildResult:
    files: list[RepoFileHint]
    rendered_messages: list[dict]
    token_estimate: int
```

要求：
1. repo context 不能再只是单个文本 blob
2. 必须能知道“为什么选中这个文件”
3. 必须能记录 score / reason

## 5.3 测试
新增 `test_repo_map.py` 的最小结构测试：
1. `RepoFileHint` 可构造
2. `RepoContextBuildResult` 可构造
3. 文件 reason / score / symbols 字段有效

## 5.4 验收标准
1. repo context 有结构化结果对象
2. 不影响旧接口
3. 测试通过

---

# 阶段 2：实现轻量文件排序器 RepoRanker

## 6.1 目标
先做一个“足够实用”的轻量 ranking，不一步上 Aider 全量 PageRank。

## 6.2 要做的事

### 新建 `aicoder/context/repo_ranker.py`
提供至少这些函数：

- `collect_candidate_files(coder) -> list[str]`
- `rank_repo_files(coder, mode: str) -> list[RepoFileHint]`

### 初版 ranking 规则
按优先级给分：

1. 用户显式加入 / 当前上下文文件
2. 最近编辑文件
3. 搜索命中文件
4. 特殊重要文件
   - `README`
   - `pyproject.toml`
   - `package.json`
   - `requirements.txt`
   - `setup.py`
   - `Dockerfile`
   - `Makefile`
   - `AGENTS.md`
   - `CLAUDE.md`
5. 目录浅层、名字匹配当前任务的文件

### 要求
1. 初版允许不做 symbol graph
2. 必须可测试
3. `reason` 必须写清楚，例如：
   - `focused`
   - `recently_edited`
   - `important_root_file`
   - `search_hit`

## 6.3 测试
在 `test_repo_map.py` 中新增：
1. 重要根文件优先
2. focused files 分数高于普通文件
3. 不同 mode 下候选数量可不同
4. reason 正确

## 6.4 验收标准
1. 有真实 ranking，不再是空 repo context
2. 能输出 ranked `RepoFileHint`
3. 测试通过

---

# 阶段 3：实现 Repo Renderer

## 7.1 目标
把 ranked 文件提示渲染成紧凑的 LLM context，而不是全文堆砌。

## 7.2 要做的事

### 新建 `aicoder/context/repo_renderer.py`
至少实现：

- `render_repo_context(hints: list[RepoFileHint], budget_tokens: int, mode: str) -> RepoContextBuildResult`

### 渲染规则
每个文件渲染为紧凑摘要，建议格式：

- path
- reason
- optional symbols
- optional short snippet

示例输出风格：
- `src/app.py — focused, recently_edited`
- `Contains: main(), build_context(), invoke_graph()`
- `Snippet: def main(...):`

### 要求
1. 不允许默认输出整个文件全文
2. snippet 必须短
3. 必须在 budget 内裁剪
4. 初版 budget 可以用粗略 token estimate

## 7.3 测试
新增：
1. budget 小时只保留高分文件
2. render 后消息非空
3. snippet 不会无限长
4. act 模式下 repo context 比 sniff 更小

## 7.4 验收标准
1. repo context 可以被稳定渲染
2. 渲染结果受 budget 控制
3. 测试通过

---

# 阶段 4：真正实现 build_repo_context()

## 8.1 目标
把 `ContextPacker` 里的 repo slot 从空壳变成真正可用能力。

## 8.2 要做的事

### 修改 `aicoder/context/repo_map.py`
当前接口保留：

- `build_repo_context(coder, mode: str, budget_tokens: int) -> list[dict]`

但内部要改为：
1. collect candidates
2. rank
3. render
4. 返回 messages

### 建议主流程
- `ranked = rank_repo_files(coder, mode)`
- `result = render_repo_context(ranked, budget_tokens, mode)`
- `return result.rendered_messages`

### 要求
1. 保持对 `ContextPacker` 兼容
2. 失败时 graceful fallback 到 `[]`
3. 不允许因 repo context 失败让主链崩溃

## 8.3 测试
补 `test_repo_map.py`：
1. build_repo_context 返回消息
2. 空仓库/无 map 时安全返回
3. budget 生效
4. sniff/plan/act 三模式输出差异真实存在

## 8.4 验收标准
1. `build_repo_context()` 真正可用
2. `ContextPacker` 主链已真实消费它
3. 测试通过

---

# 阶段 5：让 focused_file_tokens 真正生效

## 9.1 目标
把文件全文上下文也纳入预算系统，而不是只有 history / trace / repo。

## 9.2 要做的事

### 修改 `aicoder/context/packer.py`
对 `build_chat_files_messages(coder)` 的结果应用 budget。

建议新增 helper：

- `_trim_focused_files(messages, budget_tokens) -> list[dict]`

### 规则
1. 优先保留最近 / focused 文件
2. 超预算时裁剪旧文件或长文件内容
3. act 模式可比 sniff/plan 保留更多 focused file 内容

### 要求
1. `focused_file_tokens` 必须真实参与裁剪
2. 不能只在 trace 里显示，必须真影响 packed context
3. 不允许破坏 current messages / user_input

## 9.3 测试
新增 `test_repo_context_budget.py`：
1. focused file budget 小时会裁剪
2. recent focused file 更容易保留
3. act 模式 focused file 容量更大
4. repo budget 和 focused file budget 不互相混淆

## 9.4 验收标准
1. `focused_file_tokens` 真正生效
2. `pack_context()` 输出发生真实变化
3. 测试通过

---

# 阶段 6：细化 mode-specific context policy

## 10.1 目标
让三模式的 context 不只是大小不同，而是“内容策略不同”。

## 10.2 要做的事

### 修改 `aicoder/context/policies.py`
在现有 budget 上，补充 policy 语义，例如：

```python
@dataclass(frozen=True)
class ContextPolicy:
    repo_detail_level: str
    include_snippets: bool
    include_symbols: bool
    focused_file_preference: str
```

### 建议三模式差异

#### sniff
- repo_map_tokens: 大
- include_symbols: True
- include_snippets: 少量
- focused_file_tokens: 小
- 目标：广度扫描

#### plan
- repo_map_tokens: 中
- include_symbols: True
- include_snippets: 中
- focused_file_tokens: 中
- 目标：聚焦分析

#### act
- repo_map_tokens: 小
- include_symbols: 少量
- include_snippets: 最少
- focused_file_tokens: 大
- 目标：最小背景 + 大文件正文

### 要求
1. 这些差异必须接入 repo rank/render/packer
2. 不允许只写配置不使用
3. 必须能被 trace / dump 看出来

## 10.3 测试
新增 `test_mode_context_policy.py`：
1. sniff 比 act 拥有更大 repo context
2. act 比 sniff 拥有更大 focused file context
3. plan 在两者之间
4. trace_context 可见模式差异

## 10.4 验收标准
1. 三模式 context 策略有真实差异
2. 差异体现在最终 packed context 中
3. 测试通过

---

# 阶段 7：补调试与可观测性

## 11.1 目标
让 repo context 和 focused file budget 的效果可见。

## 11.2 要做的事

### 修改 `aicoder/debug/context_trace.py`
新增输出：
- repo selected file count
- repo selected top file reasons
- focused file budget before/after
- repo budget utilization

### 修改 `aicoder/debug/dump_helpers.py`
增强：
- `dump_packed_context()` 增加 repo layer / focused files layer 预览
- 如有必要新增：
  - `dump_repo_context(coder, mode)`

## 11.3 测试
补 `test_debug_modules.py`：
1. trace_context 能看到 repo 层统计
2. dump_packed_context 能看到 repo/focused file 层
3. 不同 mode 下 trace 差异可见

## 11.4 验收标准
1. 新上下文策略可被 trace/dump
2. 调试输出可测试
3. 测试通过

---

## 6. 具体文件修改清单

### 新增文件
- `aicoder/context/repo_types.py`
- `aicoder/context/repo_ranker.py`
- `aicoder/context/repo_renderer.py`
- `aicoder/tests/test_repo_map.py`
- `aicoder/tests/test_repo_context_budget.py`
- `aicoder/tests/test_mode_context_policy.py`

### 重点修改文件
- `aicoder/context/repo_map.py`
- `aicoder/context/policies.py`
- `aicoder/context/packer.py`
- `aicoder/debug/context_trace.py`
- `aicoder/debug/dump_helpers.py`

### 可选少量修改
- `aicoder/modes/config.py`
- `aicoder/coders/message_builder.py`

---

## 7. 提交粒度要求

GLM 必须按以下粒度提交：

1. `feat: add structured repo context types and ranking`
2. `feat: render ranked repo context within budget`
3. `feat: wire real repo context into context packer`
4. `feat: enforce focused file budget in packed context`
5. `feat: add mode-specific repo context policies`
6. `chore: extend context trace and dump helpers for repo context`

每一步都要：
- 修改代码
- 跑测试
- 输出变更说明
- 当前阶段通过后再进入下一阶段

---

## 8. 每阶段完成后的测试命令

优先运行：

```bash
pytest aicoder/tests/test_repo_map.py
pytest aicoder/tests/test_repo_context_budget.py
pytest aicoder/tests/test_mode_context_policy.py
pytest aicoder/tests/test_context_packer.py
pytest aicoder/tests/test_debug_modules.py
pytest aicoder/tests/test_regression_end_to_end.py
```

阶段性回归：

```bash
pytest aicoder/tests/ -x
```

最小回归集合：

```bash
pytest aicoder/tests/test_context_packer.py aicoder/tests/test_history_view.py aicoder/tests/test_condense.py aicoder/tests/test_debug_modules.py
```

---

## 9. GLM 输出要求

每完成一个阶段，必须输出：

```md
## 阶段 N 完成报告

### 已完成
- ...

### 修改文件
- ...

### 核心实现
- ...

### 测试结果
- 运行命令：
- 通过情况：

### 风险与兼容性
- ...

### 下一阶段建议
- ...
```

---

## 10. 禁止性提醒

GLM 不允许做以下事情：

1. 不要把 repo context 做成整个仓库全文
2. 不要只按文件名排序，不给 reason / score
3. 不要让 repo budget 和 focused file budget 混在一起
4. 不要只改 trace 不改主实现
5. 不要只加配置不接入 packer
6. 不要破坏 FC / CoT 已有链路
7. 不要顺手重写 condensation
8. 不要顺手扩散到持久化 / replay
9. 不要引入大依赖
10. 不要为了通过测试而过度 mock 主逻辑

---

## 11. 实施顺序总结

严格按这个顺序做：

1. Repo 类型定义
2. RepoRanker
3. RepoRenderer
4. build_repo_context 真正接线
5. focused_file_tokens 落地
6. mode-specific context policy
7. trace / dump 增强

不得跳序，除非当前阶段被代码现实阻塞，并在报告中明确说明原因。

---

## 12. 最终交付标准

完成后必须满足：

1. repo context 不再是空壳
2. repo context 具有 ranking / reason / budget
3. focused_file_tokens 真正影响 packed context
4. sniff / plan / act 三模式的 context 差异真实可见
5. repo/focused/history 三类上下文不会互相挤爆
6. trace / dump 能解释“为什么这些文件进了上下文”
7. v1.2.3 不回归
8. 测试通过
