import { create } from "zustand";

export interface Session {
  id: string;
  title: string;
  created: string;
}

interface SessionState {
  sessions: Session[];
  activeSessionId: string | null;
  loading: boolean;

  setSessions: (sessions: Session[]) => void;
  setActiveSession: (id: string) => void;
  startNewSession: () => void;
  setLoading: (loading: boolean) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  activeSessionId: null,
  loading: false,

  setSessions(sessions) {
    set({ sessions });
  },
  setActiveSession(id) {
    set({ activeSessionId: id });
  },
  startNewSession() {
    set({ activeSessionId: null });
  },
  setLoading(loading) {
    set({ loading });
  },
}));
