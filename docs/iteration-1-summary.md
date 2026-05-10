# 迭代 1 阶段总结

生成时间: 2026-05-09

## 一句话

AiCoder 从初始代码库收敛为 LangGraph 单主链 + Ink TUI 可编译 + 基础 CI 守护的可开发状态。

## 完成项

### 里程碑 1：后端主链统一

- LangGraph Runtime 成为默认且唯一的执行路径
- Legacy `_send_message_inner()`、`run_one()`、`send_message()` 等死代码已完全移除
- `/run` 和 `/git` 走工具系统，不再绕过审批
- 权限收紧：移除 `rm/rmdir/mv/cp/sed` 自动放行，仅保留 `mkdir/touch`
- 分层上下文裁剪迁移到 graph 节点
- pytest：**363 passed**（含 6 个 E2E 联调测试）

### 里程碑 2：TUI 工程可编译

- typecheck 从 145 errors 收敛到 **0 errors**
- compiler-runtime 残留回退为普通 React 写法
- Bun 运行时假设收敛为运行时判断
- JSX 类型补齐、第三方声明补齐
- RPC 协议边界整理，产出协议文档
- build 成功

### 里程碑 3：CI 和文档闭环

- README 重写，与当前实现一致
- 核心设计文档（runtime-unification / permission-matrix / rpc-protocol / typecheck-triage）完整
- GitHub Actions CI：pytest + typecheck + build
- 冒烟验证脚本：CLI 导入、Graph 构建、--serve 启动

### P0 补充：Legacy 主链完全移除 + E2E 联调

- 移除 `_send_message_inner()`、`run_one()`、`send_message()`、`init_before_message()`
- 移除 `_process_tool_calls()`、`_process_legacy_edits()`、`_stream_response()`
- 移除 `_trim_context_for_model()`、`_context_truncate()`、`_emergency_truncate()`、`summarize_if_needed()`
- 清理 `AICODER_LANGGRAPH_RUNTIME` 环境变量残留（测试中）
- 新增 6 个 E2E 联调测试：ready 通知、input/request、input/submit、model/list、错误方法、/quit 退出

## 未完成项

1. **`process_response()` 子类覆写** — wholefile/editblock/ask coder 的 `process_response()` 保留，但当前 graph 路径不调用。后续可考虑将编辑格式解析融入 graph 节点。
2. **TUI 交互体验** — 基础可运行，但 UI 和交互细节仍在迭代
3. **context_manager 模块** — 需确认与 graph `_trim_messages()` 的集成状态

## 当前已知风险

1. API Key 未设置时 `--serve` 仍可启动（不阻塞，但首次对话会失败）
2. LangGraph checkpoint 默认不启用，会话中断不可恢复
3. TUI spawn 后端进程的清理逻辑需要更多边界测试
4. 部分 import 依赖在 Windows 和 Linux 路径处理可能有差异

## 推荐开发命令

```bash
# 后端
pip install -e ".[dev]"
pytest                          # 运行测试
python -m aicoder               # CLI 交互模式
python -m aicoder --serve       # RPC 服务模式

# TUI
cd aicoder-tui
npm install
npm run typecheck               # 类型检查
npm run build                   # 构建
npm run dev                     # 开发模式

# 冒烟验证
bash scripts/smoke_test.sh
```

## 下一阶段 Backlog

### 优先级 P0（已完成）

- ~~**完全移除 Legacy 主链**~~：已删除 `_send_message_inner()` 等全部 legacy 代码
- ~~**E2E 联调测试**~~：已新增 6 个 --serve 模式 E2E 测试

### 优先级 P1

- **上下文管理增强**：LLM 总结 → ContextManager → 紧急截断三级策略在 graph 节点中的完整实现
- **Repo Map 索引增强**：当前 `map_tokens=1024` 的 repo map 质量可以优化
- **会话持久化增强**：启用 LangGraph checkpoint，支持中断恢复

### 优先级 P2

- **TUI 架构收口**：清理 `official-ink/` 目录，收敛 Ink 自定义组件体系
- **模型切换体验**：TUI 内切换模型后的状态同步
- **错误展示**：`parse_error`、`tool/error` 在 TUI 中的友好展示

### 优先级 P3

- **更多编辑格式**：diff 格式和 architect 格式的 graph 适配
- **插件系统**：`plugins/` 目录已存在但未激活
- **国际化**：当前 CLI 消息中英混杂
