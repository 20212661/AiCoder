import React, { useMemo } from "react";
import { Box, Text } from "ink";
import { useChatStore } from "../../stores/chatStore.js";
import { MessageBlock } from "./MessageBlock.js";

const MAX_STREAMING_LINES = 20;
const MAX_STREAMING_CHARS = 2000;
const MAX_MESSAGES_DISPLAY = 200;

/**
 * Truncate streaming text to prevent terminal flooding
 */
function truncateStreamingText(text: string): {
  display: string;
  truncated: boolean;
} {
  let truncated = false;
  let display = text;

  const lines = display.split("\n");
  if (lines.length > MAX_STREAMING_LINES) {
    display = lines.slice(-MAX_STREAMING_LINES).join("\n");
    truncated = true;
  }

  if (display.length > MAX_STREAMING_CHARS) {
    display = display.slice(-MAX_STREAMING_CHARS);
    truncated = true;
  }

  return { display, truncated };
}

export function ChatView() {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingText = useChatStore((s) => s.streamingText);

  // Only render last N messages for performance
  const visibleMessages = useMemo(
    () =>
      messages.length > MAX_MESSAGES_DISPLAY
        ? messages.slice(-MAX_MESSAGES_DISPLAY)
        : messages,
    [messages],
  );

  const hasSkipped = messages.length > MAX_MESSAGES_DISPLAY;

  // Truncate streaming text
  const { display: displayStream, truncated: streamTruncated } = useMemo(
    () => (streamingText ? truncateStreamingText(streamingText) : { display: "", truncated: false }),
    [streamingText],
  );

  return (
    <Box flexDirection="column" paddingX={1}>
      {messages.length === 0 && (
        <Box flexDirection="column" paddingY={1}>
          <Text color="cyan" bold>
            AiCoder
          </Text>
          <Text dimColor>Type a message to get started.</Text>
          <Text dimColor>
            Use /help for available commands.
          </Text>
        </Box>
      )}

      {hasSkipped && (
        <Box marginBottom={1}>
          <Text dimColor>
            ... ({messages.length - MAX_MESSAGES_DISPLAY} earlier messages hidden)
          </Text>
        </Box>
      )}

      {visibleMessages.map((msg) => (
        <Box
          key={msg.id}
          flexDirection="column"
          marginBottom={1}
        >
          <Text color={msg.role === "user" ? "green" : "white"} bold>
            {msg.role === "user" ? "▸ You" : "◂ Assistant"}
          </Text>
          {msg.blocks.map((block, i) => (
            <MessageBlock key={`${msg.id}-${i}`} block={block} />
          ))}
        </Box>
      ))}

      {isStreaming && streamingText && (
        <Box flexDirection="column" marginBottom={1}>
          <Text color="white" bold>
            ◂ Assistant
          </Text>
          {streamTruncated && (
            <Text dimColor>  ... (earlier output truncated)</Text>
          )}
          <Text>{displayStream}</Text>
          <Text color="gray">▎</Text>
        </Box>
      )}

      {isStreaming && !streamingText && (
        <Box>
          <Text color="yellow">◐ thinking...</Text>
        </Box>
      )}
    </Box>
  );
}
