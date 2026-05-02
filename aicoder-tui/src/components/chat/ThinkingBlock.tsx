import { Box, Text } from "ink";

interface Props {
  content: string;
}

export function ThinkingBlock({ content }: Props) {
  return (
    <Box flexDirection="column" marginLeft={1}>
      <Text color="#ffc080" dimColor>
        {content.length > 120 ? content.slice(0, 117) + "..." : content}
      </Text>
    </Box>
  );
}
