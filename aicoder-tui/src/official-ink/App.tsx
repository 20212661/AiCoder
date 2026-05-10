import React, { useEffect, useState } from "react";
import { Box, Text, useInput, useApp } from "ink";
import { MainLayout } from "./layout/MainLayout.js";
import { useOfficialBackend, getBackendApi } from "./hooks/useOfficialBackend.js";
import { useChatStore } from "../stores/chatStore.js";

type AppState = "connecting" | "ready" | "error";

export function App() {
  const [state, setState] = useState<AppState>("connecting");
  const [errorMsg, setErrorMsg] = useState("");
  const { connect, disconnect } = useOfficialBackend();
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
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  useInput((input, key) => {
    // Escape: cancel streaming generation
    if (key.escape) {
      const store = useChatStore.getState();
      if (store.isStreaming) {
        getBackendApi()?.cancelGeneration();
        store.finalizeStream("");
      }
    }
    // Ctrl+C: during streaming, cancel generation; otherwise exit
    if (key.ctrl && input === "c") {
      const store = useChatStore.getState();
      if (store.isStreaming) {
        getBackendApi()?.cancelGeneration();
        store.finalizeStream("");
      } else {
        exit();
      }
    }
  });

  if (state === "connecting") {
    return (
      <Box flexDirection="column" paddingY={1}>
        <Text color="cyan" bold>
          AiCoder
        </Text>
        <Text dimColor>Connecting...</Text>
      </Box>
    );
  }

  if (state === "error") {
    return (
      <Box flexDirection="column" paddingY={1}>
        <Text color="red">Error: {errorMsg}</Text>
        <Text dimColor>python -m aicoder --serve</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" height="100%">
      <MainLayout />
    </Box>
  );
}