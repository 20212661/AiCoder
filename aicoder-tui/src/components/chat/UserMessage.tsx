import { Box, Text } from "../../ink/index.js";
import type { ChatMessage } from "../../stores/chatStore.js";

interface Props {
  message: ChatMessage;
}

export function UserMessage({ message }: Props) {
  const text = message.blocks.find((b) => b.type === "text")?.content ?? "";

  return (
    <Box flexDirection="column" marginTop={0}>
      <Text dim>{">"} {text}</Text>
    </Box>
  );
}
