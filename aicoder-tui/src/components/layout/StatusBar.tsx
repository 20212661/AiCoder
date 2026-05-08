import { Box, Text } from "../../ink/index.js";
import { getBackendApi } from "../../hooks/useBackend.js";
import { useChatStore } from "../../stores/chatStore.js";
import { useConfigStore } from "../../stores/configStore.js";

export function StatusBar() {
  const model = useConfigStore((s) => s.model);
  const mode = useConfigStore((s) => s.mode);
  const isStreaming = useChatStore((s) => s.isStreaming);

  const api = getBackendApi();

  return (
    <Box>
      <Text dim>? for shortcuts</Text>
      <Box flexGrow={1} />
      <Text dim color={api ? undefined : "#ff6b6b"}>
        {api ? "●" : "○"}
      </Text>
      <Text dim> </Text>
      <Text color={mode === "plan" ? "#5fb3b3" : "#f5a65b"}>
        {mode === "plan" ? "PLAN" : "ACT"}
      </Text>
      <Text dim> </Text>
      {isStreaming ? (
        <Text color="#9fcaff">● streaming</Text>
      ) : (
        <Text dim>{model}</Text>
      )}
    </Box>
  );
}
