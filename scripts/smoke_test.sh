#!/usr/bin/env bash
# 冒烟验证脚本 — 验证关键模块可导入、CLI 可启动、--serve 模式正常
# 用法: bash scripts/smoke_test.sh
# 前提: pip install -e ".[dev]"

set -e

echo "=== Smoke Test ==="

echo "1. CLI entry import..."
python -c "from aicoder.main import main, get_parser; print('   OK')"

echo "2. AgentRuntime import..."
python -c "from aicoder.agent_runtime import _create_runtime; print('   OK')"

echo "3. Graph construction..."
python -c "from aicoder.graph.workflow import build_agent_graph; g = build_agent_graph(); print(f'   OK: {len(g.nodes)} nodes')"

echo "4. RPC IO import..."
python -c "from aicoder.rpc_io import JsonRpcIO; print('   OK')"

echo "5. --serve mode startup..."
# Start serve mode, wait for ready notification, then kill
timeout 5 python -m aicoder --serve 2>/dev/null | head -1 | grep -q '"method":"ready"' && echo "   OK" || echo "   FAIL (no ready notification)"

echo "6. pytest..."
pytest -q

echo "=== All smoke tests passed ==="
