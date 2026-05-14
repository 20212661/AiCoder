import { create } from "zustand";

export type AppMode = "sniff" | "plan" | "act";

/** True when the mode is read-only (sniff or plan). */
export function isReadOnlyMode(mode: AppMode): boolean {
  return mode === "sniff" || mode === "plan";
}

export interface AppConfig {
  model: string;
  mode: AppMode;
  theme: string;
  showSidebar: boolean;
  showThinking: boolean;
  /** Derived: true when mode is "plan" or "sniff". Prefer using isReadOnlyMode(mode). */
  planMode: boolean;
  yolo: boolean;
  commands: string[];
  availableModels: string[];
  workspaceRoot?: string;
  phase: string;
}

interface ConfigState extends AppConfig {
  setModel: (model: string) => void;
  setMode: (mode: AppMode) => void;
  setTheme: (theme: string) => void;
  toggleSidebar: () => void;
  toggleThinking: () => void;
  toggleYolo: () => void;
  setCommands: (commands: string[]) => void;
  setAvailableModels: (models: string[]) => void;
  setWorkspaceRoot: (root: string) => void;
  updateFromBackend: (params: Record<string, unknown>) => void;
}

export const useConfigStore = create<ConfigState>((set) => ({
  model: "unknown",
  mode: "act",
  phase: "idle",
  theme: "dark",
  showSidebar: false,
  showThinking: false,
  planMode: false,
  yolo: false,
  commands: [],
  availableModels: [],

  setModel(model) {
    set({ model });
  },
  setMode(mode) {
    set({ mode, planMode: isReadOnlyMode(mode) });
  },
  setTheme(theme) {
    set({ theme });
  },
  toggleSidebar() {
    set((s) => ({ showSidebar: !s.showSidebar }));
  },
  toggleThinking() {
    set((s) => ({ showThinking: !s.showThinking }));
  },
  toggleYolo() {
    set((s) => ({ yolo: !s.yolo }));
  },
  setCommands(commands) {
    set({ commands });
  },
  setAvailableModels(availableModels) {
    set({ availableModels });
  },
  setWorkspaceRoot(workspaceRoot) {
    set({ workspaceRoot });
  },
  updateFromBackend(params) {
    const updates: Partial<AppConfig> = {};
    if (params.model && typeof params.model === "string") updates.model = params.model;
    // mode is the canonical field — always derive planMode from it
    if (params.mode === "sniff" || params.mode === "plan" || params.mode === "act") {
      updates.mode = params.mode;
      updates.planMode = isReadOnlyMode(params.mode);
    }
    if (typeof params.yolo === "boolean") updates.yolo = params.yolo;
    if (typeof params.phase === "string") updates.phase = params.phase;
    set(updates);
  },
}));
