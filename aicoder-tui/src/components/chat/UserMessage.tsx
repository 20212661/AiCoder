import { Box, Text } from "ink";
import type { ChatMessage } from "../../stores/chatStore.js";

interface Props {
  message: ChatMessage;
}

export function UserMessage({ message }: Props) {
  const text = message.blocks.find((b) => b.type === "text")?.content ?? "";

  return (
    <Box flexDirection="column" marginY={0}>
      <Text color="#666">{"─".repeat(2)}</Text>
      <Text>{text}</Text>
    </Box>
  );
}
