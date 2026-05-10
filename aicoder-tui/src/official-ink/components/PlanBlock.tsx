import React from "react";
import { Box, Text } from "ink";

interface PlanBlockProps {
  content: string;
}

export function PlanBlock({ content }: PlanBlockProps) {
  const lines = content.split("\n");

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="magenta"
      paddingX={1}
    >
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return null;

        const isHeading =
          trimmed.startsWith("Plan:") ||
          trimmed.startsWith("Findings:") ||
          trimmed.startsWith("Next step:");

        return (
          <Text key={i} color={isHeading ? "magenta" : "white"} bold={isHeading}>
            {trimmed}
          </Text>
        );
      })}
    </Box>
  );
}

/**
 * Check if text contains plan-like content
 */
export function isPlanContent(text: string): boolean {
  return (
    text.includes("Plan:") ||
    text.includes("Findings:") ||
    text.includes("Next step:")
  );
}