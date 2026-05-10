import React from "react";
import { Box, Text } from "ink";
import { theme } from "../theme.js";

export interface CommandItem {
  name: string;
  description?: string;
}

interface SlashCommandMenuProps {
  commands: CommandItem[];
  selectedIndex: number;
  visible: boolean;
}

export function SlashCommandMenu({
  commands,
  selectedIndex,
  visible,
}: SlashCommandMenuProps) {
  const palette = theme.colors;

  if (!visible || commands.length === 0) return null;

  return (
    <Box flexDirection="column" paddingLeft={2} marginBottom={0}>
      {commands.slice(0, 8).map((cmd, i) => (
        <Box key={cmd.name}>
          <Text color={i === selectedIndex ? palette.primary : palette.dim}>
            {i === selectedIndex ? "▸ " : "  "}
            {cmd.name}
          </Text>
          {cmd.description && (
            <Text color={palette.dim}> — {cmd.description}</Text>
          )}
        </Box>
      ))}
      <Text dimColor>  Tab to complete · ↑↓ to navigate</Text>
    </Box>
  );
}

/**
 * Known slash commands with descriptions
 */
export const KNOWN_COMMANDS: CommandItem[] = [
  { name: "/sniff", description: "Inspect without editing (reconnaissance)" },
  { name: "/plan", description: "Switch to plan mode (read-only)" },
  { name: "/act", description: "Switch to act mode (execute)" },
  { name: "/model", description: "Change AI model" },
  { name: "/clear", description: "Clear chat history" },
  { name: "/compact", description: "Compact conversation context" },
  { name: "/yolo", description: "Toggle auto-approve mode" },
  { name: "/help", description: "Show available commands" },
  { name: "/exit", description: "Exit application" },
  { name: "/quit", description: "Exit application (alias)" },
];

/**
 * Filter commands matching a prefix
 */
export function filterCommands(
  commands: string[],
  prefix: string,
): CommandItem[] {
  if (!prefix.startsWith("/")) return [];
  const query = prefix.toLowerCase();
  // Merge known commands with backend-provided commands
  const knownMatches = KNOWN_COMMANDS.filter((cmd) =>
    cmd.name.toLowerCase().startsWith(query),
  );
  const backendMatches = commands
    .filter((cmd) => cmd.toLowerCase().startsWith(query))
    .filter(
      (cmd) => !KNOWN_COMMANDS.some((kc) => kc.name.toLowerCase() === cmd.toLowerCase()),
    )
    .map((cmd) => ({ name: cmd }));
  return [...knownMatches, ...backendMatches];
}
