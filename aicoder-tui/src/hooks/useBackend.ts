import { useEffect, useRef, useCallback } from "react";
import { RpcClient } from "../rpc/client.js";
import { createBackendApi } from "../rpc/methods.js";
import { useChatStore } from "../stores/chatStore.js";
import { useApprovalStore } from "../stores/approvalStore.js";
import { useConfigStore } from "../stores/configStore.js";
import type { BackendApi } from "../rpc/methods.js";

let rpcInstance: RpcClient | null = null;
let apiInstance: BackendApi | null = null;

export function useBackend() {
  const rpcRef = useRef<RpcClient | null>(null);
  const apiRef = useRef<BackendApi | null>(null);

  const connect = useCallback(async () => {
    const rpc = new RpcClient();
    rpcRef.current = rpc;
    rpcInstance = rpc;
    apiInstance = createBackendApi(rpc);
    apiRef.current = apiInstance;

    // Wire backend notifications to stores
    rpc.on("stream/token", (params: { text: string }) => {
      const store = useChatStore.getState();
      if (!store.isStreaming) {
        store.startAssistantMessage();
      }
      store.appendStreamToken(params.text);
    });

    rpc.on("stream/finalize", (params: { text: string }) => {
      useChatStore.getState().finalizeStream(params.text);
    });

    rpc.on("assistant/output", (params: { text: string }) => {
      const store = useChatStore.getState();
      store.startAssistantMessage();
      store.finalizeStream(params.text);
    });

    rpc.on("tool/call_started", (params: { tool: string; args: Record<string, unknown> }) => {
      useChatStore.getState().addToolCall(params.tool, params.args);
    });

    rpc.on("tool/call_finished", (params: { tool: string; result: string; success: boolean }) => {
      useChatStore.getState().updateToolResult(params.tool, params.result, params.success);
    });

    rpc.on("approval/request", (params: { id: string; question: string; diff?: string }) => {
      useApprovalStore.getState().addRequest(params);
    });

    rpc.on("status/update", (params: Record<string, unknown>) => {
      useConfigStore.getState().updateFromBackend(params);
    });

    rpc.on("ready", (params: Record<string, unknown>) => {
      useConfigStore.getState().updateFromBackend(params);
    });

    rpc.on("error", (params: { message: string }) => {
      const store = useChatStore.getState();
      if (store.isStreaming) {
        store.finalizeStream("");
      }
      store.addErrorMessage(params.message);
    });

    rpc.on("tool/error", (params: { message: string }) => {
      useChatStore.getState().addErrorMessage(params.message);
    });

    // Forward backend stderr to console for debugging
    rpc.on("stderr", (data: string) => {
      const line = data.trim();
      if (line) {
        useChatStore.getState().addErrorMessage("[backend] " + line);
      }
    });

    await rpc.connect();
  }, []);

  const disconnect = useCallback(async () => {
    await rpcRef.current?.disconnect();
    rpcRef.current = null;
    rpcInstance = null;
    apiInstance = null;
    apiRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  const getRpc = useCallback(() => rpcRef.current, []);
  const getApi = useCallback(() => apiRef.current, []);

  return {
    connect,
    disconnect,
    getRpc,
    getApi,
  };
}

export function getRpcClient(): RpcClient | null {
  return rpcInstance;
}

export function getBackendApi(): BackendApi | null {
  // First try the module-level variable (fast path)
  if (apiInstance) return apiInstance;
  // Fall back to rpcInstance
  return rpcInstance ? createBackendApi(rpcInstance) : null;
}
