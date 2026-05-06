import { Box, Text } from "../../ink/index.js";

interface Props {
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
  result?: string;
}

export function ToolCallCard({ tool, args, status, result }: Props) {
  const icon = status === "running" ? "◐" : status === "done" ? "✓" : "✗";
  const color = status === "running" ? "#9fcaff" : status === "done" ? "#7ec699" : "#ff6b6b";
  const summary = buildToolSummary(tool, args);

  return (
    <Box flexDirection="column" marginY={0}>
      <Box>
        <Text color={color}>{icon} </Text>
        <Text bold color={color}>{tool}</Text>
        {summary && <Text dim>{" " + summary}</Text>}
      </Box>
      {result && status !== "running" && (
        <Box marginLeft={2} flexDirection="column">
          {result.split("\n").slice(0, 5).map((line, i) => (
            <Text key={i} dim>{line}</Text>
          ))}
          {result.split("\n").length > 5 && (
            <Text dim>{"  ... (" + (result.split("\n").length - 5) + " more lines)"}</Text>
          )}
        </Box>
      )}
    </Box>
  );
}

function buildToolSummary(tool: string, args: Record<string, unknown>): string {
  if (tool === "run_shell" || tool === "bash") {
    return args.command ? String(args.command).slice(0, 50) : "";
  }
  if (tool === "edit_file" || tool === "write_file") {
    return args.path ? String(args.path) : "";
  }
  if (tool === "read_file") {
    return args.path ? String(args.path) : "";
  }
  return "";
}
