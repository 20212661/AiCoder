import { Box } from "ink";
import type { ChatMessage, MessageBlock } from "../../stores/chatStore.js";
import { TextBlock } from "./TextBlock.js";
import { ThinkingBlock } from "./ThinkingBlock.js";
import { CodeBlock } from "./CodeBlock.js";
import { ToolCallCard } from "../tools/ToolCallCard.js";

interface Props {
  message: ChatMessage;
}

export function AiMessage({ message }: Props) {
  return (
    <Box flexDirection="column">
      {message.blocks.map((block, i) => (
        <BlockRenderer key={i} block={block} />
      ))}
    </Box>
  );
}

function BlockRenderer({ block }: { block: MessageBlock }) {
  switch (block.type) {
    case "text":
      return <TextBlock content={block.content} />;
    case "thinking":
      return <ThinkingBlock content={block.content} />;
    case "code":
      return <CodeBlock language={block.language} content={block.content} />;
    case "tool_call":
      return (
        <ToolCallCard
          tool={block.tool}
          args={block.args}
          status={block.status}
          result={block.result}
        />
      );
    default:
      return null;
  }
}
