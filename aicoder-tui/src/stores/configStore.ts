import { create } from "zustand";

export interface AppConfig {
  model: string;
  theme: string;
  showSidebar: boolean;
  showThinking: boolean;
  planMode: boolean;
  yolo: boolean;
  commands: string[];
  availableModels: string[];
  workspaceRoot?: string;
}

interface ConfigState extends AppConfig {
  setModel: (model: string) => void;
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
    set((s) => ({ planMode: !s.planMode }));
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
    if (typeof params.planMode === "boolean") updates.planMode = params.planMode;
    set(updates);
  },
}));
