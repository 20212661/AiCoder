import React from "react";
import { Box, Text, useInput } from "ink";
import { useApprovalStore } from "../../stores/approvalStore.js";
import { getBackendApi } from "../../hooks/useBackend.js";

export function ApprovalPanel() {
  const pending = useApprovalStore((s) => s.pending);
  const respond = useApprovalStore((s) => s.respond);

  useInput((ch, key) => {
    if (!pending) return;

    if (ch === "y" || ch === "Y") {
      getBackendApi()?.approvalRespond(pending.id, true);
      respond(pending.id, true);
    } else if (ch === "n" || ch === "N" || key.escape) {
      getBackendApi()?.approvalRespond(pending.id, false);
      respond(pending.id, false);
    }
  });

  if (!pending) return null;

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="yellow"
      paddingX={1}
    >
      <Text color="yellow" bold>
        ⚠ Approval Required
      </Text>
      <Text>{pending.question}</Text>
      {pending.diff && (
        <Box flexDirection="column" marginTop={1}>
          <Text color="gray">
            {pending.diff.length > 300
              ? `${pending.diff.slice(0, 300)}...`
              : pending.diff}
          </Text>
        </Box>
      )}
      <Box marginTop={1}>
        <Text color="green">[y]</Text>
        <Text> approve </Text>
        <Text color="red">[n]</Text>
        <Text> reject </Text>
        <Text color="gray">[esc] reject</Text>
      </Box>
    </Box>
  );
}