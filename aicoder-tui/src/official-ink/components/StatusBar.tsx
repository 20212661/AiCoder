import React from "react";
import { Box, Text } from "ink";
import { useConfigStore } from "../../stores/configStore.js";
import { useChatStore } from "../../stores/chatStore.js";
import { useApprovalStore } from "../../stores/approvalStore.js";
import { theme } from "../theme.js";

export function StatusBar() {
  const model = useConfigStore((s) => s.model);
  const mode = useConfigStore((s) => s.mode);
  const phase = useConfigStore((s) => s.phase);
  const yolo = useConfigStore((s) => s.yolo);
  const workspaceRoot = useConfigStore((s) => s.workspaceRoot);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const pendingApproval = useApprovalStore((s) => s.pending);
  const msgCount = useChatStore((s) => s.messages.length);

  const palette = theme.colors;
  const isReadOnly = mode === "plan" || mode === "sniff";
  const displayMode = mode.toUpperCase();

  const sniffPhaseLabels: Record<string, string> = {
    idle: "嗅探中",
    streaming: "结构扫描",
  };
  const defaultPhase = isStreaming ? "streaming" : "idle";
  const rawPhase = phase || defaultPhase;
  const displayPhase = mode === "sniff" ? (sniffPhaseLabels[rawPhase] ?? rawPhase) : rawPhase;

  const sniffStatusTexts: Record<string, string> = {
    idle: "● 嗅探中",
    streaming: "◐ 结构扫描",
  };
  const defaultStatusText = pendingApproval
    ? "⏳ approval"
    : isStreaming
      ? "◐ streaming"
      : "● ready";
  const statusKey = pendingApproval ? "approval" : (isStreaming ? "streaming" : "idle");
  const statusText = mode === "sniff" && !pendingApproval
    ? (sniffStatusTexts[statusKey] ?? defaultStatusText)
    : defaultStatusText;

  const shortPath = workspaceRoot
    ? workspaceRoot.split(/[/\\]/).slice(-2).join("/")
    : "";

  const modeColor = isReadOnly ? palette.plan : palette.act;

  return (
    <Box borderStyle="single" borderColor={isReadOnly ? palette.plan : yolo ? palette.warning : palette.dim} paddingX={1}>
      <Box flexGrow={1}>
        <Text color={modeColor} bold>
          {displayMode}
        </Text>
        {yolo && (
          <>
            <Text> </Text>
            <Text color={palette.warning} bold>⚡YOLO</Text>
          </>
        )}
        <Text> │ </Text>
        <Text color={palette.assistant}>{model}</Text>
        <Text> │ </Text>
        <Text color={pendingApproval ? palette.warning : isStreaming ? palette.warning : palette.success}>
          {displayPhase}
        </Text>
        <Text> │ </Text>
        <Text color={pendingApproval ? palette.warning : isStreaming ? palette.warning : palette.success}>
          {statusText}
        </Text>
        {shortPath && (
          <>
            <Text> │ </Text>
            <Text color={palette.dim}>{shortPath}</Text>
          </>
        )}
        <Text> │ </Text>
        <Text color={palette.dim}>{msgCount} msgs</Text>
      </Box>
    </Box>
  );
}
