import { Box, Text, useInput } from "../../ink/index.js";
import { useApprovalStore } from "../../stores/approvalStore.js";
import { getBackendApi } from "../../hooks/useBackend.js";

export function ApprovalDialog() {
  const pending = useApprovalStore((s) => s.pending);

  useInput((input) => {
    if (!pending) return;
    const approved = input === "y" || input === "Y";
    const rejected = input === "n" || input === "N";
    if (!approved && !rejected) return;

    useApprovalStore.getState().respond(pending.id, approved);
    getBackendApi()?.approvalRespond(pending.id, approved);
  });

  if (!pending) return null;

  return (
    <Box flexDirection="column" marginY={1}>
      <Text dim>{"─".repeat(40)}</Text>
      <Text color="#ffc080">⚡ {pending.question}</Text>
      {pending.diff && (
        <Box flexDirection="column" marginLeft={2}>
          {pending.diff.split("\n").slice(0, 8).map((line, i) => {
            const color = line.startsWith("+") ? "#7ec699" : line.startsWith("-") ? "#ff6b6b" : undefined;
            return <Text key={i} color={color} dim={!color}>{line}</Text>;
          })}
        </Box>
      )}
      <Box>
        <Text color="#7ec699" bold>[Y]</Text>
        <Text dim> allow  </Text>
        <Text color="#ff6b6b" bold>[N]</Text>
        <Text dim> deny</Text>
      </Box>
    </Box>
  );
}
