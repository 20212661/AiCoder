import { Box, Text } from "ink";

interface Props {
  output: string;
  success: boolean;
}

export function ToolResultCard({ output, success }: Props) {
  return (
    <Box flexDirection="column" marginLeft={2}>
      <Text color={success ? "green" : "red"}>
        {success ? "✓ Success" : "✗ Failed"}
      </Text>
      <Box flexDirection="column">
        {output.split("\n").map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
      </Box>
    </Box>
  );
}
