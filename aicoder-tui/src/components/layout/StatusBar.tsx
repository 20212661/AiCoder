import { Box, Text } from "../../ink/index.js";
import { useConfigStore } from "../../stores/configStore.js";
import { useChatStore } from "../../stores/chatStore.js";
import { getBackendApi } from "../../hooks/useBackend.js";

export function StatusBar() {
  const model = useConfigStore((s) => s.model);
  const isStreaming = useChatStore((s) => s.isStreaming);

  const api = getBackendApi();

  return (
    <Box>
      <Text dim>? for shortcuts</Text>
      <Box flexGrow={1} />
      <Text dim color={api ? undefined : "#ff6b6b"}>{api ? "●" : "○"}</Text>
      <Text dim> </Text>
      {isStreaming && (
        <Text color="#9fcaff">◐ streaming</Text>
      )}
      {!isStreaming && (
        <Text dim>{model}</Text>
      )}
    </Box>
  );
}
