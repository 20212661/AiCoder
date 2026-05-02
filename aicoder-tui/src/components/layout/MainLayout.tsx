import { Box, useApp } from "ink";
import { ChatPanel } from "../chat/ChatPanel.js";
import { StatusBar } from "./StatusBar.js";
import { ApprovalDialog } from "../approval/ApprovalDialog.js";
import { useKeyBindings } from "../../hooks/useKeyBindings.js";
import { useChatStore } from "../../stores/chatStore.js";

export function MainLayout() {
  const { exit } = useApp();

  useKeyBindings({
    clearChat: () => useChatStore.getState().clearChat(),
    quit: () => exit(),
  });

  return (
    <Box flexDirection="column">
      <ChatPanel />
      <ApprovalDialog />
      <StatusBar />
    </Box>
  );
}
