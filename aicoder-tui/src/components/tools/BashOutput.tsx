import { Box, Text } from "ink";

interface Props {
  command: string;
  output: string;
  exitCode: number | null;
}

export function BashOutput({ command, output, exitCode }: Props) {
  const failed = exitCode !== null && exitCode !== 0;

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Text dimColor>$ {command}</Text>
      <Box flexDirection="column">
        {output.split("\n").map((line, i) => (
          <Text key={i} color={failed ? "red" : undefined}>
            {line}
          </Text>
        ))}
      </Box>
      {exitCode !== null && (
        <Text color={failed ? "red" : "green"}>
          exit code: {exitCode}
        </Text>
      )}
    </Box>
  );
}
