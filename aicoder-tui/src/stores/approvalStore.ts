import { create } from "zustand";

export interface ApprovalRequest {
  id: string;
  question: string;
  diff?: string;
}

interface ApprovalState {
  pending: ApprovalRequest | null;
  queue: ApprovalRequest[];

  addRequest: (req: ApprovalRequest) => void;
  respond: (id: string, approved: boolean) => void;
  clear: () => void;
}

export const useApprovalStore = create<ApprovalState>((set, get) => ({
  pending: null,
  queue: [],

  addRequest(req) {
    const { pending } = get();
    if (pending) {
      set((s) => ({ queue: [...s.queue, req] }));
    } else {
      set({ pending: req });
    }
  },

  respond(id, approved) {
    const { pending, queue } = get();
    if (pending?.id === id) {
      set({
        pending: queue.length > 0 ? queue[0] : null,
        queue: queue.slice(1),
      });
    }
    return approved;
  },

  clear() {
    set({ pending: null, queue: [] });
  },
}));
