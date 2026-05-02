import { Box, Text } from "ink";
import { useApprovalStore } from "../../stores/approvalStore.js";

export function ApprovalDialog() {
  const pending = useApprovalStore((s) => s.pending);
  if (!pending) return null;

  return (
    <Box flexDirection="column" marginY={1}>
      <Text color="#ffc080">{pending.question}</Text>
      {pending.diff && (
        <Box flexDirection="column" marginTop={0}>
          {pending.diff.split("\n").slice(0, 10).map((line, i) => (
            <Text key={i} dimColor>{line}</Text>
          ))}
        </Box>
      )}
      <Box marginTop={0}>
        <Text color="#9fcaff" bold>[Y]</Text>
        <Text> yes  </Text>
        <Text color="#ff6b6b" bold>[N]</Text>
        <Text> no</Text>
      </Box>
    </Box>
  );
}
