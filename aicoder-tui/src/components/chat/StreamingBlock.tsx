import { Box, Text } from "ink";
import { WhimsicalSpinner } from "../common/Spinner.js";

interface Props {
  text: string;
}

export function StreamingBlock({ text }: Props) {
  if (!text) return <WhimsicalSpinner />;

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
      <Text>{lastLine}</Text>
    </Box>
  );
}
