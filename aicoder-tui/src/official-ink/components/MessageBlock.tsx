import React from "react";
import { Box, Text } from "ink";
import type { MessageBlock as MessageBlockType } from "../../stores/chatStore.js";
import { ToolCallCard } from "./ToolCallCard.js";
import { PlanBlock, isPlanContent } from "./PlanBlock.js";

interface MessageBlockProps {
  block: MessageBlockType;
}

export function MessageBlock({ block }: MessageBlockProps) {
  switch (block.type) {
    case "text": {
      // Detect plan content and render with PlanBlock
      if (isPlanContent(block.content)) {
        return <PlanBlock content={block.content} />;
      }
      return <Text>{block.content}</Text>;
    }

    case "thinking":
      return (
        <Box paddingLeft={1}>
          <Text color="gray" italic>
            {block.content}
          </Text>
        </Box>
      );

    case "code":
      return (
        <Box flexDirection="column" paddingLeft={1}>
          <Text color="gray">```{block.language}</Text>
          <Text>{block.content}</Text>
          <Text color="gray">```</Text>
        </Box>
      );

    case "tool_call":
      return (
        <ToolCallCard
          tool={block.tool}
          status={block.status}
          args={block.args}
          result={block.result}
        />
      );

    case "tool_output": {
      const lines = block.content.split("\n");
      const truncated = lines.length > 4;
      const display = truncated
        ? lines.slice(0, 4).join("\n")
        : block.content;
      const tooLong = display.length > 200;
      return (
        <Box paddingLeft={2} flexDirection="column">
          <Text color="gray">
            {tooLong ? display.slice(0, 200) : display}
          </Text>
          {(truncated || tooLong) && (
            <Text dimColor>  ... (output truncated)</Text>
          )}
        </Box>
      );
    }

    case "error":
      return (
        <Box paddingLeft={1}>
          <Text color="red">✗ {block.content}</Text>
        </Box>
      );

    default:
      return null;
  }
}
