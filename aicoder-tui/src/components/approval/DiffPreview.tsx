import { Box, Text } from "ink";
import { renderDiffLines } from "../../renderers/diff.js";

interface Props {
  diff: string;
}

export function DiffPreview({ diff }: Props) {
  const rendered = renderDiffLines(diff);

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="gray"
      paddingX={1}
    >
      {rendered.split("\n").map((line, i) => (
        <Text key={i}>{line}</Text>
      ))}
    </Box>
  );
}
