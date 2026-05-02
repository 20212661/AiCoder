import { Box, Text } from "ink";

interface Props {
  text: string;
}

export function StreamingCursor({ text }: Props) {
  const lines = text.split("\n");
  const lastLine = lines.at(-1) ?? "";

  return (
    <Box flexDirection="column">
      {lines.length > 1 && (
        <Box flexDirection="column">
          {lines.slice(0, -1).map((line, i) => (
            <Text key={i}>{line}</Text>
          ))}
        </Box>
      )}
      <Box>
        <Text>{lastLine}</Text>
        <Text color="cyan">▎</Text>
      </Box>
    </Box>
  );
}
