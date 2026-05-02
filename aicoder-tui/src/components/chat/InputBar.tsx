import { useState } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { useChatStore } from "../../stores/chatStore.js";
import { getBackendApi } from "../../hooks/useBackend.js";

export function InputBar() {
  const [input, setInput] = useState("");
  const isStreaming = useChatStore((s) => s.isStreaming);

  function handleSubmit(value: string) {
    const text = value.trim();
    if (!text) return;
    useChatStore.getState().addUserMessage(text);
    getBackendApi()?.submitInput(text);
    setInput("");
  }

  return (
    <Box marginTop={1}>
      <Text color="#9fcaff">{"> "} </Text>
      {isStreaming ? (
        <Text dimColor>waiting for response...</Text>
      ) : (
        <TextInput
          value={input}
          onChange={setInput}
          onSubmit={handleSubmit}
          placeholder="type your message..."
        />
      )}
    </Box>
  );
}
