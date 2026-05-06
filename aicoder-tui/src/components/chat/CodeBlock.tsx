import { Box, Text } from "../../ink/index.js";
import { renderCodeBlock } from "../../renderers/markdown.js";

interface Props {
  language: string;
  content: string;
}

export function CodeBlock({ language, content }: Props) {
  const rendered = renderCodeBlock(content, language);
  const lines = rendered.split("\n");

  return (
    <Box flexDirection="column">
      {lines.map((line, i) => (
        <Text key={i}>  {line}</Text>
      ))}
    </Box>
  );
}
