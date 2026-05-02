import { Box } from "ink";
import { useChatStore } from "../../stores/chatStore.js";
import { UserMessage } from "./UserMessage.js";
import { AiMessage } from "./AiMessage.js";
import { StreamingBlock } from "./StreamingBlock.js";
import { InputBar } from "./InputBar.js";

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingText = useChatStore((s) => s.streamingText);

  return (
    <Box flexDirection="column">
      {messages.map((msg) =>
        msg.role === "user" ? (
          <UserMessage key={msg.id} message={msg} />
        ) : (
          <AiMessage key={msg.id} message={msg} />
        ),
      )}
      {isStreaming && <StreamingBlock text={streamingText} />}
      <InputBar />
    </Box>
  );
}
