import { useCallback } from "react";
import { useChatStore } from "../stores/chatStore.js";

export function useStreaming() {
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingText = useChatStore((s) => s.streamingText);

  const startStreaming = useCallback(() => {
    useChatStore.getState().startAssistantMessage();
  }, []);

  const appendToken = useCallback((token: string) => {
    useChatStore.getState().appendStreamToken(token);
  }, []);

  const finalize = useCallback((fullText: string) => {
    useChatStore.getState().finalizeStream(fullText);
  }, []);

  return { isStreaming, streamingText, startStreaming, appendToken, finalize };
}
