import React, { useState, useMemo, useCallback } from "react";
import { Box, Text, useInput } from "ink";
import { useChatStore } from "../../stores/chatStore.js";
import { useApprovalStore } from "../../stores/approvalStore.js";
import { useConfigStore } from "../../stores/configStore.js";
import { getBackendApi } from "../../hooks/useBackend.js";
import { SlashCommandMenu, filterCommands } from "./SlashCommandMenu.js";
import { ModelPicker } from "./ModelPicker.js";
import { theme } from "../theme.js";

interface InputBoxProps {
  disabled?: boolean;
}

// Input history store (module-level)
const history: string[] = [];
let historyIdx = -1;

export function InputBox({ disabled = false }: InputBoxProps) {
  const [input, setInput] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [showMenu, setShowMenu] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const commands = useConfigStore((s) => s.commands);

  // Filter commands when input starts with /
  const filteredCommands = useMemo(
    () => filterCommands(commands, input),
    [input, commands],
  );

  // Determine if menu should show
  const menuVisible = showMenu && filteredCommands.length > 0 && !disabled && !isStreaming;

  const handleSlashCommand = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      const lower = trimmed.toLowerCase();
      switch (lower) {
        case "/model":
          setShowModelPicker(true);
          return true;
        case "/clear":
          useChatStore.getState().clearChat();
          return true;
        case "/plan":
          useConfigStore.getState().setMode("plan");
          getBackendApi()?.submitInput("/plan").catch(() => {});
          return true;
        case "/act":
          useConfigStore.getState().setMode("act");
          getBackendApi()?.submitInput("/act").catch(() => {});
          return true;
        case "/sniff":
          useConfigStore.getState().setMode("sniff");
          getBackendApi()?.submitInput("/sniff").catch(() => {});
          return true;
        case "/yolo":
          getBackendApi()?.submitInput("/yolo").catch(() => {});
          return true;
        case "/help":
          useChatStore.getState().addToolOutput(
            [
              "Available commands:",
              "  /sniff   - 嗅探仓库结构与构石痕迹（只读调查）",
              "  /plan    - Create a plan (read-only analysis)",
              "  /act     - Execute changes (full tool access)",
              "  /model   - Change AI model",
              "  /clear   - Clear chat history",
              "  /compact - Compact conversation context",
              "  /yolo    - Toggle auto-approve mode",
              "",
              "  /help    - Show this help",
              "  /exit    - Exit application",
              "",
              "Keyboard shortcuts:",
              "  ↑↓      - Navigate history / command menu",
              "  Tab     - Autocomplete slash command",
              "  Esc     - Cancel streaming generation",
              "  Ctrl+C  - Exit application",
            ].join("\n"),
          );
          return true;
        case "/exit":
        case "/quit":
          getBackendApi()?.submitInput("/exit").catch(() => {});
          return true;
        case "/compact":
          getBackendApi()?.submitInput("/compact").catch(() => {});
          useChatStore.getState().addToolOutput("Compacting conversation context...");
          return true;
        default:
          // Forward unknown slash commands to backend
          if (lower.startsWith("/")) {
            getBackendApi()?.submitInput(trimmed).catch(() => {});
            return true;
          }
          return false;
      }
    },
    [],
  );

  useInput((ch, key) => {
    // Model picker takes priority when visible
    if (showModelPicker) return;

    if (disabled || isStreaming) {
      // Allow Escape to cancel during streaming
      if (isStreaming && key.escape) {
        getBackendApi()?.cancelGeneration();
        useChatStore.getState().finalizeStream("");
      }
      return;
    }

    // When approval panel is active, skip input processing
    const pendingApproval = useApprovalStore.getState().pending;
    if (pendingApproval) return;

    // Tab: autocomplete with selected command
    if (key.tab && menuVisible) {
      const cmd = filteredCommands[selectedIdx];
      if (cmd) {
        setInput(cmd.name + " ");
        setShowMenu(false);
        setSelectedIdx(0);
      }
      return;
    }

    // Arrow up/down: navigate command menu or history
    if (menuVisible) {
      if (key.upArrow) {
        setSelectedIdx((prev) =>
          prev > 0 ? prev - 1 : filteredCommands.length - 1,
        );
        return;
      }
      if (key.downArrow) {
        setSelectedIdx((prev) =>
          prev < filteredCommands.length - 1 ? prev + 1 : 0,
        );
        return;
      }
    } else {
      // History navigation (when not in slash menu)
      if (key.upArrow && history.length > 0) {
        const newIdx = Math.min(historyIdx + 1, history.length - 1);
        historyIdx = newIdx;
        setInput(history[newIdx] ?? "");
        return;
      }
      if (key.downArrow && historyIdx >= 0) {
        const newIdx = historyIdx - 1;
        historyIdx = newIdx;
        setInput(newIdx >= 0 ? (history[newIdx] ?? "") : "");
        return;
      }
    }

    if (key.return) {
      const text = input.trim();
      if (!text) return;

      // Add to history
      if (history[0] !== text) {
        history.unshift(text);
        if (history.length > 100) history.pop();
      }
      historyIdx = -1;

      // Handle slash commands
      if (text.startsWith("/")) {
        const handled = handleSlashCommand(text);
        if (handled) {
          setInput("");
          setShowMenu(false);
          setSelectedIdx(0);
          return;
        }
      }

      // Normal message
      const store = useChatStore.getState();
      store.addUserMessage(text);
      setInput("");
      setShowMenu(false);
      setSelectedIdx(0);
      const api = getBackendApi();
      api?.submitInput(text).catch(() => {});
      return;
    }

    if (key.backspace || key.delete) {
      setInput((prev) => {
        const next = prev.slice(0, -1);
        if (next.startsWith("/") && next.length > 0) {
          setShowMenu(true);
          setSelectedIdx(0);
        } else {
          setShowMenu(false);
        }
        return next;
      });
      return;
    }

    if (ch && !key.ctrl && !key.meta) {
      setInput((prev) => {
        const next = prev + ch;
        if (next.startsWith("/")) {
          setShowMenu(true);
          setSelectedIdx(0);
        } else {
          setShowMenu(false);
        }
        return next;
      });
    }
  });

  const pendingApproval = useApprovalStore.getState().pending;
  const isDisabled = disabled || isStreaming || !!pendingApproval;
  const palette = theme.colors;

  return (
    <Box flexDirection="column">
      {/* Slash command menu */}
      <SlashCommandMenu
        commands={filteredCommands}
        selectedIndex={selectedIdx}
        visible={menuVisible}
      />

      {/* Model picker */}
      <ModelPicker
        visible={showModelPicker}
        onClose={() => setShowModelPicker(false)}
      />

      {/* Input line */}
      <Box borderStyle="single" borderColor={pendingApproval ? palette.warning : palette.dim} paddingX={1}>
        <Text color={palette.primary} bold>
          {">"}
        </Text>
        <Text> </Text>
        {pendingApproval ? (
          <Text color={palette.warning}>waiting for approval...</Text>
        ) : isStreaming ? (
          <Text color={palette.warning}>◐ streaming... (Esc to cancel)</Text>
        ) : (
          <Text>{input}</Text>
        )}
        {!isDisabled && <Text color={palette.dim}>▎</Text>}
      </Box>
    </Box>
  );
}
