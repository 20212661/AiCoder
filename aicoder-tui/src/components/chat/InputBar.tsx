import { useEffect, useState } from "react";
import { Box, Text } from "../../ink/index.js";
import useInput from "../../ink/hooks/use-input.js";
import { getBackendApi } from "../../hooks/useBackend.js";
import { useChatStore } from "../../stores/chatStore.js";
import { useConfigStore } from "../../stores/configStore.js";
import { getModelPickerPageSize, ModelPicker } from "./ModelPicker.js";
import { SlashCommandMenu } from "./SlashCommandMenu.js";

function getCommandPrefix(input: string): string | null {
  if (!input.startsWith("/")) return null;
  const spaceIdx = input.indexOf(" ");
  return spaceIdx === -1 ? input : input.slice(0, spaceIdx);
}

function filterCommands(prefix: string, commands: string[]): string[] {
  return commands.filter((cmd) => cmd.startsWith(prefix));
}

function applySelectedCommand(selectedCommand: string): string {
  return `${selectedCommand} `;
}

export function InputBar() {
  const [input, setInput] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showMenu, setShowMenu] = useState(false);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [modelPickerIndex, setModelPickerIndex] = useState(0);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelPickerError, setModelPickerError] = useState("");
  const isStreaming = useChatStore((s) => s.isStreaming);
  const commands = useConfigStore((s) => s.commands);
  const currentModel = useConfigStore((s) => s.model);
  const availableModels = useConfigStore((s) => s.availableModels);
  const setAvailableModels = useConfigStore((s) => s.setAvailableModels);
  const setModel = useConfigStore((s) => s.setModel);

  const isSlashMode = input.startsWith("/");
  const prefix = getCommandPrefix(input);
  const filteredCommands =
    isSlashMode && prefix && !modelPickerOpen ? filterCommands(prefix, commands) : [];

  useEffect(() => {
    if (modelPickerOpen) {
      setShowMenu(false);
      return;
    }

    if (!isSlashMode) {
      setShowMenu(false);
      setSelectedIndex(0);
    } else if (filteredCommands.length > 0) {
      setShowMenu(true);
      if (selectedIndex >= filteredCommands.length) {
        setSelectedIndex(0);
      }
    } else {
      setShowMenu(false);
    }
  }, [filteredCommands.length, input, isSlashMode, modelPickerOpen, selectedIndex]);

  useEffect(() => {
    if (!modelPickerOpen) return;

    const api = getBackendApi();
    if (!api) {
      setModelPickerError("Backend not ready yet, please wait...");
      setLoadingModels(false);
      return;
    }

    let cancelled = false;
    setLoadingModels(true);
    setModelPickerError("");

    api
      .listModels()
      .then((result) => {
        if (cancelled) return;
        setAvailableModels(result.models);
        if (result.currentModel) {
          setModel(result.currentModel);
        }
        const nextIndex = result.models.findIndex((name) => name === result.currentModel);
        setModelPickerIndex(nextIndex >= 0 ? nextIndex : 0);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setModelPickerError(`Failed to load models: ${err.message}`);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingModels(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [modelPickerOpen, setAvailableModels, setModel]);

  function submitText(text: string) {
    const api = getBackendApi();
    useChatStore.getState().addUserMessage(text);

    if (!api) {
      useChatStore.getState().addErrorMessage("Backend not ready yet, please wait...");
      return;
    }

    api.submitInput(text).catch((err: Error) => {
      useChatStore.getState().addErrorMessage(`Submit failed: ${err.message}`);
    });
  }

  function openModelPicker() {
    setInput("/model");
    setShowMenu(false);
    setModelPickerOpen(true);
    setModelPickerError("");
  }

  function closeModelPicker() {
    setModelPickerOpen(false);
    setModelPickerError("");
  }

  useInput((ch, key) => {
    if (isStreaming) return;

    if (modelPickerOpen) {
      if (key.escape) {
        closeModelPicker();
        return;
      }

      if (key.upArrow && availableModels.length > 0) {
        setModelPickerIndex((prev) => {
          const pageSize = getModelPickerPageSize();
          const pageStart = Math.floor(prev / pageSize) * pageSize;
          const pageEnd = Math.min(pageStart + pageSize - 1, availableModels.length - 1);
          return prev <= pageStart ? pageEnd : prev - 1;
        });
        return;
      }

      if (key.downArrow && availableModels.length > 0) {
        setModelPickerIndex((prev) => {
          const pageSize = getModelPickerPageSize();
          const pageStart = Math.floor(prev / pageSize) * pageSize;
          const pageEnd = Math.min(pageStart + pageSize - 1, availableModels.length - 1);
          return prev >= pageEnd ? pageStart : prev + 1;
        });
        return;
      }

      if (key.leftArrow && availableModels.length > 0) {
        setModelPickerIndex((prev) => {
          const pageSize = getModelPickerPageSize();
          const pageStart = Math.floor(prev / pageSize) * pageSize;
          if (pageStart === 0) return prev;
          const offsetInPage = prev - pageStart;
          const nextPageStart = Math.max(0, pageStart - pageSize);
          const nextPageEnd = Math.min(
            nextPageStart + pageSize - 1,
            availableModels.length - 1,
          );
          return Math.min(nextPageStart + offsetInPage, nextPageEnd);
        });
        return;
      }

      if (key.rightArrow && availableModels.length > 0) {
        setModelPickerIndex((prev) => {
          const pageSize = getModelPickerPageSize();
          const pageStart = Math.floor(prev / pageSize) * pageSize;
          const nextPageStart = pageStart + pageSize;
          if (nextPageStart >= availableModels.length) return prev;
          const offsetInPage = prev - pageStart;
          const nextPageEnd = Math.min(
            nextPageStart + pageSize - 1,
            availableModels.length - 1,
          );
          return Math.min(nextPageStart + offsetInPage, nextPageEnd);
        });
        return;
      }

      if (key.return) {
        const selectedModel = availableModels[modelPickerIndex];
        if (!selectedModel || loadingModels) return;
        closeModelPicker();
        setInput("");
        submitText(`/model ${selectedModel}`);
        return;
      }

      return;
    }

    if (key.escape) {
      if (showMenu) {
        setShowMenu(false);
      }
      return;
    }

    if (key.upArrow) {
      if (showMenu && filteredCommands.length > 0) {
        setSelectedIndex(
          (prev) => (prev - 1 + filteredCommands.length) % filteredCommands.length,
        );
      }
      return;
    }

    if (key.downArrow) {
      if (showMenu && filteredCommands.length > 0) {
        setSelectedIndex((prev) => (prev + 1) % filteredCommands.length);
      }
      return;
    }

    if (key.tab) {
      if (showMenu && filteredCommands.length > 0) {
        setInput(applySelectedCommand(filteredCommands[selectedIndex]));
        setShowMenu(false);
      }
      return;
    }

    if (key.return) {
      if (showMenu && filteredCommands.length > 0) {
        const selected = filteredCommands[selectedIndex];
        if (selected === "/model") {
          openModelPicker();
          return;
        }
        if (prefix === selected) {
          setShowMenu(false);
          setInput("");
          submitText(selected);
        } else {
          setInput(applySelectedCommand(selected));
          setShowMenu(false);
        }
        return;
      }

      const text = input.trim();
      if (!text) return;

      if (text === "/model") {
        openModelPicker();
        return;
      }

      submitText(text);
      setInput("");
      return;
    }

    if (key.backspace || key.delete) {
      setInput((prev) => prev.slice(0, -1));
      return;
    }

    if (ch && !key.ctrl && !key.meta) {
      setInput((prev) => prev + ch);
    }
  });

  if (isStreaming) {
    return (
      <Box>
        <Text dimColor>{"-".repeat(80)}</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Text dimColor>{"-".repeat(80)}</Text>
      <ModelPicker
        currentModel={currentModel}
        error={modelPickerError}
        loading={loadingModels}
        models={availableModels}
        selectedIndex={modelPickerIndex}
        visible={modelPickerOpen}
      />
      <SlashCommandMenu
        commands={filteredCommands}
        selectedIndex={selectedIndex}
        visible={showMenu}
      />
      <Box>
        <Text color="claude">{">"} </Text>
        <Text>{input}</Text>
        <Text inverse>{" "}</Text>
      </Box>
      <Text dimColor>{"-".repeat(80)}</Text>
    </Box>
  );
}
