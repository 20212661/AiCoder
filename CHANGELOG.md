# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.8.0] — 2026-05-14

### Added

- **CLI interactive mode for LangChain runtime** (`aicoder --runtime langchain`)
  - Enters interactive loop when `--message` is omitted
  - `/quit`, `/exit` to exit; `/clear` to clear history
  - Unsupported slash commands produce a warning without calling the agent
  - Session JSON persisted after each successful turn via `persist_langchain_turn()`
  - Agent errors: `tool_error` output, no session save, loop continues
  - `KeyboardInterrupt` and `EOFError` handled identically to legacy runtime
- **`aicoder/langchain_runtime/session.py`** — `persist_langchain_turn()` helper extracted from inline code
- **`aicoder/langchain_runtime/interactive.py`** — `run_langchain_interactive()` CLI interactive loop
- **17 new tests** (84 total, up from 67) covering interactive loop, session helper, and integration

### Changed

- `base_coder.py` langchain branch: `--message` path now uses `persist_langchain_turn()`; no-message path calls `run_langchain_interactive()` instead of printing a warning
- Updated `docs/langchain-runtime-status.md` — Phase 5 from planned to implemented; regression matrix updated to 122 tests across 4 files

### Limitations (unchanged)

- TUI `--serve langchain` interactive mode not supported (`rpc_io` loop not adapted)
- Streaming not supported (synchronous `agent.invoke()`)
- `interrupt` / `checkpointer` not integrated — next phase entry point
- Middleware rate-limit / retry modules degrade to no-op (`langchain` version constraint)

## [0.7.0] — 2025-05-14

### Added

- **Experimental LangChain runtime** (`--runtime langchain --message "..."`)
  - Opt-in bypass using `langgraph.prebuilt.create_react_agent`
  - `StructuredTool` wrappers delegating to existing `ToolExecutor` pipeline (no direct file/shell access)
  - Error handling middleware (`wrap_tool_call`) with graceful degradation
  - Structured output (`AICoderResponse`) when agent supports `response_format`
  - Session persistence: user/assistant turns saved to session JSON
  - `recursion_limit=25` on `agent.invoke()` to prevent runaway loops
  - 67 tests, 8 design documents (approval, session/checkpoint, interactive loop, tools contract, migration)
- **Session federation module** — `TaskThread`, `SessionLink`, `FederationPolicy`, restore bundle
- **Context system** — packer, policies, condense, summarizer, repo map, snapshot
- **Debug/observability** — context trace, dump helpers, condense trace
- **Event system** — persistence (file store), replay, serializer, step store
- **Recovery** — checkpoint guard, engine, policy
- **Verification** — policy (debounce), runner (syntax check, test runner)
- **Parsers** — CoT JSON action, CoT XML tool, function calling
- **Messages** — conversion (LangChain ↔ aicoder), types
- **Modes** — config, definitions, context policy, tool trace policy
- **CI workflow** — backend, tests-core-v16x, tests-regression-v13-v15, tui

### Fixed

- **RPC E2E test stability** — resolved `BrokenPipeError`/`OSError` in `test_rpc_e2e.py`
  - Root cause: `aicoder/session/` package shadowed `aicoder/session.py` module, causing `ImportError` on `--serve` startup
  - Fix: moved `session.py` → `session/core.py`, re-exported public API from `__init__.py`
  - Test harness: pipe-close race handling, stderr diagnostics, graceful subprocess shutdown
- **Backend crash on disconnect** — transport disconnect checks and state synchronization
- **Approval blocking** — resolved blocking approval and disconnect handling

### Changed

- `RunShellArgs.timeout` typed as `int` (was `str`), auto-converted for `ToolCall.params`
- `Coder.__init__` now initializes `self.runtime = "legacy"` explicitly
- `langchain>=0.3.0` added as explicit dependency in `pyproject.toml`
- TUI: removed deprecated `useOfficialBackend`, consolidated hooks and stores
- Graph state: added federation fields (`task_thread_id`, `federation_context`, `federation_trace`)

### Design Documents (not implemented)

- LangChain runtime approval/interrupt integration
- Session/checkpoint design (thread_id mapping, side-effect recovery)
- Interactive loop design (CLI/TUI split, command handling)
- Tools contract and safety boundary
- LangChain runtime migration overall plan

## [0.6.0] — 2025-05-12

### Added

- LangGraph agent runtime with Ink TUI system
- Sniff mode for workspace reconnaissance
- Plan/act mode with mode-aware permission gating
- Structured approval request for tool executor
- Approval required for file edit and write handlers
- Slash commands, model picker, plan mode UI
- RPC improvements for TUI communication
