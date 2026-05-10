import { Box, Text } from "../../ink/index.js";

interface SlashCommandMenuProps {
  commands: string[];
  selectedIndex: number;
  visible: boolean;
}

export function SlashCommandMenu({
  commands,
  selectedIndex,
  visible,
}: SlashCommandMenuProps) {
  if (!visible || commands.length === 0) return null;

  return (
    <Box flexDirection="column" marginLeft={2}>
      {commands.map((cmd, index) => {
        const isSelected = index === selectedIndex;
        return (
          <Box key={cmd}>
            <Text>{isSelected ? ">" : " "} </Text>
            <Text color={isSelected ? "claude" : undefined} bold={isSelected}>
              {cmd}
            </Text>
          </Box>
        );
      })}
    </Box>
  );
}
