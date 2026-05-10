import { useEffect, useState } from "react";
import Box from "./design-system/ThemedBox.js";
import Text from "./design-system/ThemedText.js";
import useInput from "./ink/hooks/use-input.js";
import useApp from "./ink/hooks/use-app.js";
import { ChatPanel } from "./components/chat/ChatPanel.js";
import { StatusBar } from "./components/layout/StatusBar.js";
import { ApprovalDialog } from "./components/approval/ApprovalDialog.js";
import { useBackend } from "./hooks/useBackend.js";
import { useChatStore } from "./stores/chatStore.js";
import { useConfigStore } from "./stores/configStore.js";
import { getBackendApi } from "./hooks/useBackend.js";

type AppState = "connecting" | "ready" | "error";

export function App() {
  const [state, setState] = useState<AppState>("connecting");
  const [errorMsg, setErrorMsg] = useState("");
  const { connect, disconnect, getRpc } = useBackend();
  const { exit } = useApp();

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

  useInput((input, key) => {
    if (key.escape) {
      const store = useChatStore.getState();
      if (store.isStreaming) {
        getBackendApi()?.cancelGeneration();
        store.finalizeStream("");
      }
    }
    if (key.ctrl && input === "c") {
      exit();
    }
  });

  if (state === "connecting") {
    return (
      <Box flexDirection="column" paddingY={1}>
        <Text bold color="claude">AiCoder</Text>
        <Text dimColor>Connecting...</Text>
      </Box>
    );
  }

  if (state === "error") {
    return (
      <Box flexDirection="column" paddingY={1}>
        <Text color="error">Error: {errorMsg}</Text>
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
    <Box flexDirection="column">
      <Box>
        <Box flexDirection="column">
          <Text color="claude">{"   ▄█▄    "}</Text>
          <Text color="claude">{" ▄█████▄  "}</Text>
          <Text color="claude">{"▀███████▀ "}</Text>
        </Box>
        <Box flexDirection="column" justifyContent="center">
          <Text bold color="claude">{" 屎山生成器 v0.6.0"}</Text>
          <Text dimColor>{" " + model + " · AI Pair Programming"}</Text>
          <Text dimColor>{" " + process.cwd().replace(/\\/g, "/")}</Text>
        </Box>
      </Box>
      <Text dimColor>{"─".repeat(80)}</Text>
    </Box>
  );
}
