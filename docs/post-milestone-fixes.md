# 里程碑收尾修复清单

## 目的

这份文档用于承接三大里程碑完成后的收尾工作，聚焦“已经基本完成，但仍有遗漏或不一致”的问题。

当前项目的核心整改已经基本到位：

- 后端主链已切到 `AgentRuntime`
- TUI 已可 `typecheck`
- TUI 已可 `build`
- CI 已覆盖后端测试和 TUI 编译检查

但仍有几项值得尽快补齐的问题，避免后续 AI 或开发者误判项目状态。

---

## 总体结论

优先级建议如下：

1. **先修 README 与事实不一致问题**
2. **再补“主链切换成功”的行为测试**
3. **最后补 RPC 的最小完整回合 E2E**
4. **顺手清理 `base_coder.py` 中遗留的无用状态和注释**

---

## 问题 1：README 与当前代码状态不一致

### 问题描述

当前 `README.md` 中还有几处信息已经过期，和当前代码状态不一致：

1. 后端测试数量写的是 `360`，但现在实际是 `363`
2. README 仍写“stderr 输出调试日志”，但 `rpc_io.py` 中已去除相关调试输出
3. README 写“Legacy `_send_message_inner()` 主循环仍保留为降级备用”，但当前代码中该方法已经删除
4. README 链接到了 `LICENSE`，但仓库根目录下并不存在该文件

### 受影响文件

- `README.md`

### 修改建议

#### 1. 更新测试数量

将：

```md
后端测试（360 个）
```

改为更稳妥的写法，避免以后每次数量变化都要改文档，例如：

```md
后端测试（当前已覆盖核心运行时、权限、工具、RPC 与图工作流）
```

如果你坚持保留数字，也应更新为：

```md
后端测试（363 个）
```

推荐第一种，更不容易再次过期。

#### 2. 修正 stderr 描述

将：

```md
后端通过 stdin/stdout 收发 JSON-RPC 2.0 消息，stderr 输出调试日志。
```

改为：

```md
后端通过 stdin/stdout 收发 JSON-RPC 2.0 消息。stderr 仅保留异常或必要诊断输出，不参与协议通信。
```

#### 3. 修正 Legacy 主循环说明

将：

```md
Legacy `_send_message_inner()` 主循环仍保留为降级备用，默认已不走
```

改为：

```md
旧的 Legacy 主循环已从默认执行路径中移除，当前统一通过 `AgentRuntime` 驱动 LangGraph 主链。
```

如果你想更明确，也可以写：

```md
Legacy `_send_message_inner()` 等旧主循环方法已删除，当前只保留 LangGraph 主链。
```

#### 4. 处理 LICENSE 问题

有两个可选方案：

##### 方案 A：补一个 `LICENSE` 文件

如果你准备继续以 Apache-2.0 对外发布，建议直接在仓库根目录新增标准 Apache 2.0 license 文件。

##### 方案 B：暂时移除 README 中的链接

如果你还没准备好正式 license 文件，就把：

```md
[Apache-2.0](LICENSE)
```

改成纯文本：

```md
Apache-2.0
```

推荐方案 A，更完整。

### 验收标准

- README 中不再出现过期事实
- README 中的链接都能打开
- 新开发者不会因为 README 被误导

---

## 问题 2：`test_coder_uses_agent_runtime` 验证力度不足

### 问题描述

当前测试：

- `aicoder/tests/test_coder_init.py`

中的 `test_coder_uses_agent_runtime()` 只是检查旧方法是否不存在：

- `run_one`
- `_send_message_inner`
- `send_message`

这不能真正证明 `Coder.run()` 已正确委托给 `AgentRuntime`。

也就是说：

- 它能证明“旧方法没了”
- 但不能证明“新主链真的在跑”

### 受影响文件

- `aicoder/tests/test_coder_init.py`

### 修改建议

把这个测试改成**行为验证**。

### 推荐测试思路

#### 测试目标

验证 `Coder.run(with_message=...)` 时：

1. 会调用 `_create_runtime(coder)`
2. 返回的 runtime 会执行 `run_user_turn(message)`
3. `Coder.run()` 会返回 runtime 的结果

### 推荐实现方式

使用 `unittest.mock.patch` patch：

```python
from unittest.mock import MagicMock, patch
```

伪代码结构：

```python
def test_coder_run_delegates_to_agent_runtime():
    coder = Coder.create(
        main_model=Model("machao-flash"),
        edit_format="whole",
        io=InputOutput(pretty=False, yes=True),
    )

    fake_runtime = MagicMock()
    fake_runtime.run_user_turn.return_value = "ok-from-runtime"

    with patch("aicoder.agent_runtime._create_runtime", return_value=fake_runtime) as mock_factory:
        result = coder.run(with_message="hello")

    mock_factory.assert_called_once_with(coder)
    fake_runtime.run_user_turn.assert_called_once_with("hello")
    assert result == "ok-from-runtime"
```

### 可补充的第二个测试

还可以补一个交互模式下的测试，验证 `get_input()` 返回用户输入时，也会调用 runtime。

如果你想先控制范围，至少先补上 `with_message` 这条路径。

### 验收标准

- 测试真正验证“委托行为”
- 不只是验证旧方法是否消失

---

## 问题 3：RPC E2E 缺少“完整一轮交互”覆盖

### 问题描述

当前 RPC E2E 已覆盖：

- `ready`
- `input/request`
- `input/submit`
- `model/list`
- 未知 method 错误
- `/quit`

但还没有覆盖一条最关键的链路：

**提交一条正常输入后，后端实际完成一轮 assistant 输出或状态推进。**

这意味着：

- `--serve` 能启动，已验证
- 基础 RPC method 能回包，已验证
- 但“真正完成一轮对话”的 E2E 还没自动守住

### 受影响文件

- `aicoder/tests/test_rpc_e2e.py`

### 修改建议

新增一个最小完整回合测试。

### 推荐测试目标

在 `--serve` 模式下：

1. 收到 `ready`
2. 收到 `input/request`
3. 提交一条普通输入
4. 确认后续至少出现以下其中之一：
   - `status/update`
   - `stream/token`
   - `stream/finalize`
   - `assistant/output`

### 注意点

当前真实模型调用可能依赖外部 API，不适合做真正联网 E2E。

因此更稳妥的方案是：

#### 方案 A：注入 mock model / fake response

如果现有代码结构允许，给 serve 测试提供一个 fake 模型输出，让这条链能稳定完成。

#### 方案 B：至少验证状态推进

如果暂时不方便 mock LLM，就先验证：

- 发送 `input/submit`
- 后续能收到 `status/update`

这虽然不算完整 assistant 输出，但至少能证明后端确实开始处理这轮请求。

### 推荐新增测试示意

可新增类似：

```python
def test_submit_input_triggers_status_update(...):
    ...
```

或者：

```python
def test_submit_input_emits_assistant_or_stream_event(...):
    ...
```

### 验收标准

- RPC E2E 不再只验证启动和控制指令
- 至少覆盖一轮真实输入后的处理链

---

## 问题 4：`base_coder.py` 中还有一批遗留状态未清理

### 问题描述

当前后端主链已经完成迁移，但 `aicoder/coders/base_coder.py` 里还保留了不少明显来自 legacy 方案的字段或注释：

- `EMERGENCY_KEEP_MESSAGES`
- `partial_response_content`
- `multi_response_content`
- `reflected_message`
- `num_reflections`
- `max_reflections`
- `shell_commands`
- `summarizer`
- `_context_mgr`
- 文件尾部未使用的 `ToolCall` import

这些问题目前**不一定会造成功能错误**，但会造成两个后果：

1. 后续 AI 或开发者误以为旧链仍在起作用
2. 后续继续收口时，理解成本变高

### 受影响文件

- `aicoder/coders/base_coder.py`

### 修改建议

#### 1. 删除已不再使用的字段

先通过搜索确认这些字段确实没有被 graph 主链或其他模块引用，再删：

- `partial_response_content`
- `multi_response_content`
- `reflected_message`
- `num_reflections`
- `max_reflections`
- `shell_commands`
- `summarizer`
- `_context_mgr`

#### 2. 删除无用常量

如果 `EMERGENCY_KEEP_MESSAGES` 已不再被引用，也一起删除。

#### 3. 删除文件尾部未使用 import

当前：

```python
from ..tools.result import ToolCall
```

若未使用，应删除。

#### 4. 修正过时注释

例如：

```python
self._context_mgr = None  # initialised lazily in _trim_context_for_model
```

如果对应方法已经不存在，这类注释也应一并清理。

### 验收标准

- `base_coder.py` 不再保留大批误导性的 legacy 状态
- 注释与当前实现一致
- 删除后测试仍通过

---

## 推荐执行顺序

建议按这个顺序补：

1. 修 README
2. 补 `test_coder_uses_agent_runtime` 的行为测试
3. 补 RPC 最小完整回合 E2E
4. 清理 `base_coder.py` 遗留状态

这个顺序的原因是：

- README 修复最直接影响使用者
- 行为测试和 E2E 测试能先把回归保护补上
- 最后再做代码清理，风险更低

---

## 推荐验证命令

每完成一项后，至少运行：

```powershell
pytest
cd aicoder-tui
cmd /c npm run typecheck
cmd /c npm run build
```

如果只改 README，可不必全量跑，但建议至少保持最终提交前全量验证一次。

---

## 给 AI 的执行提示词

如果你准备把这份收尾任务继续交给 AI，可以直接使用下面这段：

```text
请根据 docs/post-milestone-fixes.md 执行剩余修复项。

执行要求：
1. 先阅读文档中提到的相关文件。
2. 优先处理 README 不一致问题。
3. 再把 test_coder_uses_agent_runtime 改成真正的行为验证。
4. 再补一个最小 RPC 完整回合 E2E。
5. 最后清理 base_coder.py 中未使用的 legacy 状态和无用注释。
6. 每完成一项都说明修改了哪些文件、为什么这么改。
7. 最后运行 pytest、aicoder-tui 的 typecheck 和 build，并汇报结果。

不要扩大范围，不要顺手重构无关模块。
```

