import { useCallback } from "react";
import { useApprovalStore } from "../stores/approvalStore.js";
import { getBackendApi } from "./useBackend.js";

export function useApproval() {
  const pending = useApprovalStore((s) => s.pending);

  const respond = useCallback((id: string, approved: boolean) => {
    useApprovalStore.getState().respond(id, approved);
    const api = getBackendApi();
    if (api) {
      api.approvalRespond(id, approved);
    }
  }, []);

  return { pending, respond };
}
