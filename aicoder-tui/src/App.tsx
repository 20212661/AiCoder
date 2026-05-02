import { useEffect, useState } from "react";
import { Box, Text } from "ink";
import { ChatPanel } from "./components/chat/ChatPanel.js";
import { StatusBar } from "./components/layout/StatusBar.js";
import { ApprovalDialog } from "./components/approval/ApprovalDialog.js";
import { useBackend } from "./hooks/useBackend.js";
import { useChatStore } from "./stores/chatStore.js";
import { useConfigStore } from "./stores/configStore.js";
import { WhimsicalSpinner } from "./components/common/Spinner.js";

type AppState = "connecting" | "ready" | "error";

export function App() {
  const [state, setState] = useState<AppState>("connecting");
  const [errorMsg, setErrorMsg] = useState("");
  const { connect, disconnect, getRpc } = useBackend();

  useEffect(() => {
    async function init() {
      try {
        await connect();
        setState("ready");
      } catch (err) {
        setState("error");
        setErrorMsg(err instanceof Error ? err.message : String(err));
      }
    }
    init();
    return () => { disconnect(); };
  }, [connect, disconnect, getRpc]);

  if (state === "connecting") {
    return (
      <Box flexDirection="column" paddingY={1}>
        <Text bold color="#9fcaff">AiCoder</Text>
        <WhimsicalSpinner />
      </Box>
    );
  }

  if (state === "error") {
    return (
      <Box flexDirection="column" paddingY={1}>
        <Text color="#ff6b6b">Error: {errorMsg}</Text>
        <Text dimColor>python -m aicoder --serve</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      <WelcomeBanner />
      <ChatPanel />
      <ApprovalDialog />
      <StatusBar />
    </Box>
  );
}

function WelcomeBanner() {
  const messages = useChatStore((s) => s.messages);
  const model = useConfigStore((s) => s.model);

  if (messages.length > 0) return null;

  return (
    <Box flexDirection="column" marginY={1}>
      <Text bold color="#9fcaff">AiCoder v0.6.0</Text>
      <Text dimColor>Model: {model}   Mode: ACT</Text>
      <Text dimColor>{"─".repeat(40)}</Text>
      <Text dimColor>Type a message to start chatting.</Text>
    </Box>
  );
}
