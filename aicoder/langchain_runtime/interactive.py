"""LangChain runtime CLI interactive loop."""

from __future__ import annotations

from typing import Any


def run_langchain_interactive(coder: Any):
    """Run a CLI interactive loop using the LangChain agent runtime."""
    from .agent import run_langchain_agent
    from .session import persist_langchain_turn

    while True:
        try:
            inchat = coder.get_inchat_relative_files()
            ui = coder.io.get_input(
                coder.root, inchat, [],
                coder.commands.get_commands() if coder.commands else [],
                set(),
            )
        except EOFError:
            return None
        except KeyboardInterrupt:
            coder.keyboard_interrupt()
            continue

        if not (ui and ui.strip()):
            continue

        stripped = ui.strip().lower()
        if stripped in ("/quit", "/exit"):
            return None

        if stripped == "/clear":
            coder.done_messages = []
            coder.cur_messages = []
            coder.io.tool_output("History cleared.")
            continue

        if ui.startswith("/"):
            coder.io.tool_warning(
                f"Unsupported command in LangChain interactive mode: {ui.split()[0]}"
            )
            continue

        try:
            text = run_langchain_agent(coder, ui)
        except KeyboardInterrupt:
            coder.keyboard_interrupt()
            continue
        except Exception as e:
            coder.io.tool_error(f"LangChain runtime error: {e}")
            continue

        coder.io.print_assistant_output(text)
        persist_langchain_turn(coder, ui, text)
