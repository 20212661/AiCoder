import { create } from "zustand";

export interface AppConfig {
  model: string;
  mode: "plan" | "act";
  theme: string;
  showSidebar: boolean;
  showThinking: boolean;
  planMode: boolean;
  yolo: boolean;
  commands: string[];
  availableModels: string[];
  workspaceRoot?: string;
  phase: string;
}

interface ConfigState extends AppConfig {
  setModel: (model: string) => void;
  setMode: (mode: "plan" | "act") => void;
  setPlanMode: (planMode: boolean) => void;
  setTheme: (theme: string) => void;
  toggleSidebar: () => void;
  toggleThinking: () => void;
  togglePlanMode: () => void;
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
    set({ mode, planMode: mode === "plan" });
  },
  setPlanMode(planMode) {
    set({ planMode, mode: planMode ? "plan" : "act" });
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
  togglePlanMode() {
    set((s) => ({ planMode: !s.planMode, mode: !s.planMode ? "plan" : "act" }));
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
    if (params.mode === "plan" || params.mode === "act") updates.mode = params.mode;
    if (typeof params.planMode === "boolean") updates.planMode = params.planMode;
    if (!updates.mode && typeof params.planMode === "boolean") {
      updates.mode = params.planMode ? "plan" : "act";
    }
    if (typeof params.yolo === "boolean") updates.yolo = params.yolo;
    if (typeof params.phase === "string") updates.phase = params.phase;
    set(updates);
  },
}));
