import { useEffect, useRef, useCallback } from "react";
import { RpcClient } from "../rpc/client.js";
import { createBackendApi } from "../rpc/methods.js";
import { useChatStore } from "../stores/chatStore.js";
import { useApprovalStore } from "../stores/approvalStore.js";
import { useToolStore } from "../stores/toolStore.js";
import { useConfigStore } from "../stores/configStore.js";
import type { BackendApi } from "../rpc/methods.js";

let rpcInstance: RpcClient | null = null;
let apiInstance: BackendApi | null = null;

export function useBackend() {
  const rpcRef = useRef<RpcClient | null>(null);

  const connect = useCallback(async () => {
    const rpc = new RpcClient();
    rpcRef.current = rpc;
    rpcInstance = rpc;
    apiInstance = createBackendApi(rpc);

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
      useToolStore.getState().startTool(params.tool, params.args);
      useChatStore.getState().addToolCall(params.tool, params.args);
    });

    rpc.on("tool/call_finished", (params: { tool: string; result: string; success: boolean }) => {
      useToolStore.getState().finishTool(params.tool, params.result, params.success);
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

    await rpc.connect();
  }, []);

  const disconnect = useCallback(async () => {
    await rpcRef.current?.disconnect();
    rpcRef.current = null;
    rpcInstance = null;
    apiInstance = null;
  }, []);

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    connect,
    disconnect,
    getRpc: () => rpcRef.current,
    getApi: () => apiInstance,
  };
}

export function getRpcClient(): RpcClient | null {
  return rpcInstance;
}

export function getBackendApi(): BackendApi | null {
  return apiInstance;
}
