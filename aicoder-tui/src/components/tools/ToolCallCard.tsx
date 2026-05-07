import { Box, Text } from "../../ink/index.js";
import { useConfigStore } from "../../stores/configStore.js";

interface Props {
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
  result?: string;
}

export function ToolCallCard({ tool, args, status, result }: Props) {
  const planMode = useConfigStore((s) => s.planMode);
  const icon = status === "running" ? "..." : status === "done" ? "+" : "!";
  const color = status === "running" ? "#9fcaff" : status === "done" ? "#7ec699" : "#ff6b6b";
  const summary = buildToolSummary(tool, args);
  const detailLines = result ? buildDetailLines(tool, result, planMode) : [];

  return (
    <Box flexDirection="column" marginY={0}>
      <Box>
        <Text color={color}>{icon} </Text>
        <Text bold color={color}>{tool}</Text>
        {summary ? <Text dim>{" " + summary}</Text> : null}
      </Box>
      {detailLines.length > 0 && status !== "running" ? (
        <Box marginLeft={2} flexDirection="column">
          {detailLines.map((line, index) => (
            <Text key={index} dim>{line}</Text>
          ))}
        </Box>
      ) : null}
    </Box>
  );
}

function buildToolSummary(tool: string, args: Record<string, unknown>): string {
  if (tool === "run_shell" || tool === "bash") {
    return args.command ? String(args.command).slice(0, 50) : "";
  }
  if (tool === "edit_file" || tool === "write_file" || tool === "read_file") {
    return args.path ? String(args.path) : "";
  }
  return "";
}

function buildDetailLines(tool: string, result: string, planMode: boolean): string[] {
  const lines = result.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length === 0) return [];

  if (planMode) {
    return [summarizeForPlan(tool, lines)];
  }

  const preview = lines.slice(0, 5);
  if (lines.length > 5) {
    preview.push(`... (${lines.length - 5} more lines)`);
  }
  return preview;
}

function summarizeForPlan(tool: string, lines: string[]): string {
  const first = lines[0];
  if (tool === "list_files") return "Repository scan completed.";
  if (tool === "read_file") return "File content inspected.";
  if (tool === "search_files") return first;
  if (tool === "list_code_defs") return first;
  if (tool === "run_shell") return first;
  return first;
}
