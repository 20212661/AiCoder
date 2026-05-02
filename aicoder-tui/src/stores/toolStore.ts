import { create } from "zustand";

export interface ToolExecution {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
  output?: string;
  startTime: number;
  endTime?: number;
}

interface ToolState {
  executions: ToolExecution[];
  activeCount: number;

  startTool: (tool: string, args: Record<string, unknown>) => string;
  finishTool: (tool: string, output: string, success: boolean) => void;
  clear: () => void;
}

let toolIdCounter = 0;

export const useToolStore = create<ToolState>((set) => ({
  executions: [],
  activeCount: 0,

  startTool(tool, args) {
    const id = `tool-${Date.now()}-${++toolIdCounter}`;
    const exec: ToolExecution = {
      id,
      tool,
      args,
      status: "running",
      startTime: Date.now(),
    };
    set((s) => ({
      executions: [...s.executions, exec],
      activeCount: s.activeCount + 1,
    }));
    return id;
  },

  finishTool(tool, output, success) {
    set((s) => ({
      executions: s.executions.map((e) =>
        e.tool === tool && e.status === "running"
          ? {
              ...e,
              status: success ? "done" : "error",
              output,
              endTime: Date.now(),
            }
          : e,
      ),
      activeCount: Math.max(0, s.activeCount - 1),
    }));
  },

  clear() {
    set({ executions: [], activeCount: 0 });
  },
}));
