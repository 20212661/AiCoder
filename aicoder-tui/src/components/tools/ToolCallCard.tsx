import { Box, Text } from "ink";

interface Props {
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
  result?: string;
}

export function ToolCallCard({ tool, args, status, result }: Props) {
  const icon = status === "running" ? "..." : status === "done" ? "+" : "x";

  // Build compact summary
  const summary = buildToolSummary(tool, args);

  return (
    <Box flexDirection="column" marginY={0}>
      <Box>
        <Text dimColor>{icon} </Text>
        <Text bold color="#9fcaff">{tool}</Text>
        <Text dimColor>{summary ? ` ${summary}` : ""}</Text>
      </Box>
      {result && status !== "running" && (
        <Box marginLeft={2} flexDirection="column">
          {result.split("\n").slice(0, 8).map((line, i) => (
            <Text key={i} dimColor>{line}</Text>
          ))}
          {result.split("\n").length > 8 && (
            <Text dimColor>  ... ({result.split("\n").length - 8} more lines)</Text>
          )}
        </Box>
      )}
    </Box>
  );
}

function buildToolSummary(tool: string, args: Record<string, unknown>): string {
  if (tool === "run_shell" || tool === "bash") {
    return args.command ? String(args.command).slice(0, 60) : "";
  }
  if (tool === "edit_file" || tool === "write_file") {
    return args.path ? String(args.path) : "";
  }
  if (tool === "read_file") {
    return args.path ? String(args.path) : "";
  }
  return "";
}
