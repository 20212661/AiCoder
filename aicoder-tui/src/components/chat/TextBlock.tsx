import { Box, Text } from "../../ink/index.js";
import { renderInlineMarkdown } from "../../renderers/markdown.js";

interface Props {
  content: string;
}

export function TextBlock({ content }: Props) {
  const lines = content.split("\n");
  return (
    <Box flexDirection="column">
      {lines.map((line, i) => (
        <Text key={i}>{renderInlineMarkdown(line)}</Text>
      ))}
    </Box>
  );
}
