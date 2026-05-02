import { Box, Text } from "ink";
import { renderDiffLines } from "../../renderers/diff.js";

interface Props {
  filePath: string;
  diff: string;
}

export function FileDiffView({ filePath, diff }: Props) {
  const rendered = renderDiffLines(diff);

  return (
    <Box flexDirection="column" marginY={0}>
      <Text bold color="magenta">
        📄 {filePath}
      </Text>
      <Box flexDirection="column">
        {rendered.split("\n").map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
      </Box>
    </Box>
  );
}
