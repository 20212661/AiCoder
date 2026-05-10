import React from "react";
import { Box, Text } from "ink";

const MAX_RESULT_LINES = 6;
const MAX_RESULT_CHARS = 300;
const MAX_ARG_VALUE = 60;

export interface ToolCallCardProps {
  tool: string;
  status: "running" | "done" | "error";
  args?: Record<string, unknown>;
  result?: string;
}

export function ToolCallCard({ tool, status, args, result }: ToolCallCardProps) {
  const statusIcon =
    status === "running" ? "◐" : status === "done" ? "●" : "✗";
  const statusColor =
    status === "running" ? "yellow" : status === "done" ? "green" : "red";
  const statusLabel =
    status === "running" ? "running" : status === "done" ? "done" : "error";

  const argsSummary = args
    ? Object.entries(args)
        .slice(0, 3)
        .map(([k, v]) => `${k}: ${String(v).slice(0, MAX_ARG_VALUE)}`)
        .join(", ")
    : "";

  // Truncate result: limit by lines and chars
  let truncatedResult = result ?? "";
  let isTruncated = false;

  if (truncatedResult) {
    const lines = truncatedResult.split("\n");
    if (lines.length > MAX_RESULT_LINES) {
      truncatedResult = lines.slice(0, MAX_RESULT_LINES).join("\n");
      isTruncated = true;
    }
    if (truncatedResult.length > MAX_RESULT_CHARS) {
      truncatedResult = truncatedResult.slice(0, MAX_RESULT_CHARS);
      isTruncated = true;
    }
  }

  return (
    <Box flexDirection="column" paddingLeft={1}>
      <Box>
        <Text color={statusColor}>{statusIcon} </Text>
        <Text bold>{tool}</Text>
        <Text> </Text>
        <Text color={statusColor}>{statusLabel}</Text>
      </Box>
      {argsSummary && (
        <Box paddingLeft={2}>
          <Text color="gray">{argsSummary}</Text>
        </Box>
      )}
      {truncatedResult && (
        <Box paddingLeft={2} flexDirection="column">
          <Text color="gray">{truncatedResult}</Text>
          {isTruncated && (
            <Text dimColor>  ... (output truncated)</Text>
          )}
        </Box>
      )}
    </Box>
  );
}
