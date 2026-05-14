import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import { useConfigStore } from "../../stores/configStore.js";
import { getBackendApi } from "../../hooks/useBackend.js";

interface ModelPickerProps {
  visible: boolean;
  onClose: () => void;
}

export function ModelPicker({ visible, onClose }: ModelPickerProps) {
  const availableModels = useConfigStore((s) => s.availableModels);
  const currentModel = useConfigStore((s) => s.model);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Fetch models from backend when picker opens
  useEffect(() => {
    if (!visible) {
      setError("");
      return;
    }
    setSelectedIdx(0);
    setError("");

    const fetchModels = async () => {
      const api = getBackendApi();
      if (!api) return;

      // Only fetch if we don't have models yet
      if (useConfigStore.getState().availableModels.length > 0) return;

      setLoading(true);
      try {
        const result = await api.listModels();
        if (result?.models && Array.isArray(result.models)) {
          useConfigStore.getState().setAvailableModels(result.models);
          // Also update current model from backend response
          if (result.currentModel) {
            useConfigStore.getState().setModel(result.currentModel);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load models");
      } finally {
        setLoading(false);
      }
    };
    fetchModels();
  }, [visible]);

  // Keep selectedIdx in bounds when models change
  useEffect(() => {
    if (selectedIdx >= availableModels.length && availableModels.length > 0) {
      setSelectedIdx(availableModels.length - 1);
    }
  }, [availableModels.length, selectedIdx]);

  useInput((ch, key) => {
    if (!visible) return;

    if (key.escape) {
      onClose();
      return;
    }

    if (key.upArrow) {
      setSelectedIdx((prev) =>
        prev > 0 ? prev - 1 : Math.max(availableModels.length - 1, 0),
      );
      return;
    }

    if (key.downArrow) {
      setSelectedIdx((prev) =>
        prev < availableModels.length - 1 ? prev + 1 : 0,
      );
      return;
    }

    if (key.return && availableModels.length > 0) {
      const model = availableModels[selectedIdx];
      if (model) {
        getBackendApi()?.switchModel(model);
        useConfigStore.getState().setModel(model);
      }
      onClose();
      return;
    }
  });

  if (!visible) return null;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
    >
      <Text bold color="cyan">
        Select Model
      </Text>
      {loading ? (
        <Text dimColor>Loading models...</Text>
      ) : error ? (
        <Text color="red">{error}</Text>
      ) : availableModels.length === 0 ? (
        <Text dimColor>No models available — start backend first</Text>
      ) : (
        availableModels.map((model, i) => (
          <Text
            key={model}
            color={
              i === selectedIdx
                ? "cyan"
                : model === currentModel
                  ? "green"
                  : "white"
            }
            bold={model === currentModel}
          >
            {i === selectedIdx ? "▸ " : "  "}
            {model}
            {model === currentModel ? " (current)" : ""}
          </Text>
        ))
      )}
      <Text dimColor>↑↓ select · Enter confirm · Esc cancel</Text>
    </Box>
  );
}
