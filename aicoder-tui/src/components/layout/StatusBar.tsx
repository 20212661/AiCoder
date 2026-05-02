import { Box, Text } from "ink";
import { useConfigStore } from "../../stores/configStore.js";
import { useChatStore } from "../../stores/chatStore.js";

export function StatusBar() {
  const model = useConfigStore((s) => s.model);
  const isStreaming = useChatStore((s) => s.isStreaming);

  return (
    <Box marginTop={1}>
      <Text dimColor>{model}</Text>
      {isStreaming && <Text dimColor>{"  "}streaming</Text>}
      <Box flexGrow={1} />
      <Text dimColor>esc cancel</Text>
    </Box>
  );
}
