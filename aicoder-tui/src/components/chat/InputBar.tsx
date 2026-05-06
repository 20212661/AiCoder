import { useState, useEffect } from "react";
import { Box, Text } from "../../ink/index.js";
import useInput from "../../ink/hooks/use-input.js";
import { useChatStore } from "../../stores/chatStore.js";
import { getBackendApi } from "../../hooks/useBackend.js";

export function InputBar() {
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const isStreaming = useChatStore((s) => s.isStreaming);

  // Check backend readiness periodically
  useEffect(() => {
    const check = () => {
      setConnected(!!getBackendApi());
    };
    check();
    const interval = setInterval(check, 1000);
    return () => clearInterval(interval);
  }, []);

  useInput((ch, key) => {
    if (isStreaming) return;

    if (key.return) {
      const text = input.trim();
      if (!text) return;
      useChatStore.getState().addUserMessage(text);
      const api = getBackendApi();
      if (!api) {
        useChatStore.getState().addErrorMessage("Backend not ready yet, please wait...");
        setInput("");
        return;
      }
      api.submitInput(text).catch((err: Error) => {
        useChatStore.getState().addErrorMessage(`Submit failed: ${err.message}`);
      });
      setInput("");
      return;
    }

    if (key.backspace || key.delete) {
      setInput((prev) => prev.slice(0, -1));
      return;
    }

    // Printable character (includes CJK, letters, numbers, symbols)
    if (ch && !key.ctrl && !key.meta) {
      setInput((prev) => prev + ch);
    }
  });

  if (isStreaming) {
    return (
      <Box>
        <Text dimColor>{"─".repeat(80)}</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <Text dimColor>{"─".repeat(80)}</Text>
      <Box>
        <Text color="claude">{">"} </Text>
        <Text>{input}</Text>
        <Text inverse>{" "}</Text>
      </Box>
      <Text dimColor>{"─".repeat(80)}</Text>
    </Box>
  );
}
