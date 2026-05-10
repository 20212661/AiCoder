import React from "react";
import { Box } from "ink";
import { ChatView } from "../components/ChatView.js";
import { ApprovalPanel } from "../components/ApprovalPanel.js";
import { InputBox } from "../components/InputBox.js";
import { StatusBar } from "../components/StatusBar.js";

export function MainLayout() {
  return (
    <Box flexDirection="column" height="100%">
      <Box flexGrow={1} overflow="hidden">
        <ChatView />
      </Box>
      <ApprovalPanel />
      <InputBox />
      <StatusBar />
    </Box>
  );
}