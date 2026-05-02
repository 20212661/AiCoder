import { Box, Text } from "ink";
import { useConfigStore } from "../../stores/configStore.js";
import { useSessionStore } from "../../stores/sessionStore.js";

export function Sidebar() {
  const showSidebar = useConfigStore((s) => s.showSidebar);
  const sessions = useSessionStore((s) => s.sessions);
  const activeId = useSessionStore((s) => s.activeSessionId);

  if (!showSidebar) return null;

  return (
    <Box
      flexDirection="column"
      width={24}
      borderStyle="single"
      borderColor="gray"
      paddingX={1}
    >
      <Text bold color="cyan">
        Sessions
      </Text>
      {sessions.length === 0 ? (
        <Text dimColor>No sessions</Text>
      ) : (
        sessions.map((s) => (
          <Box key={s.id}>
            <Text color={s.id === activeId ? "green" : undefined}>
              {s.id === activeId ? "▸ " : "  "}
              {s.title}
            </Text>
          </Box>
        ))
      )}
    </Box>
  );
}
