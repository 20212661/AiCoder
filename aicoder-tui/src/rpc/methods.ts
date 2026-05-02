import type { RpcClient } from "./client.js";

export function createBackendApi(rpc: RpcClient) {
  return {
    submitInput(text: string) {
      return rpc.request("input/submit", { text });
    },

    cancelGeneration() {
      return rpc.request("cancel/generation", {});
    },

    approvalRespond(id: string, approved: boolean) {
      return rpc.request("approval/respond", { id, approved });
    },

    confirmRespond(id: string, confirmed: boolean) {
      return rpc.request("confirm/respond", { id, confirmed });
    },

    listSessions() {
      return rpc.request<{ id: string; title: string; created: string }[]>(
        "session/list",
      );
    },

    resumeSession(id: string) {
      return rpc.request("session/resume", { id });
    },

    newSession() {
      return rpc.request("session/new");
    },
  };
}

export type BackendApi = ReturnType<typeof createBackendApi>;
