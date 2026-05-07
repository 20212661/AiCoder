import { create } from "zustand";

export interface TextBlock {
  type: "text";
  content: string;
}

export interface ThinkingBlock {
  type: "thinking";
  content: string;
}

export interface CodeBlock {
  type: "code";
  language: string;
  content: string;
}

export interface ToolCallBlock {
  type: "tool_call";
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
  result?: string;
}

export interface ToolOutputBlock {
  type: "tool_output";
  content: string;
}

export interface ErrorBlock {
  type: "error";
  content: string;
}

export type MessageBlock = TextBlock | ThinkingBlock | CodeBlock | ToolCallBlock | ToolOutputBlock | ErrorBlock;

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  blocks: MessageBlock[];
  timestamp: number;
}

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingText: string;
  currentAssistantId: string | null;

  addUserMessage: (text: string) => void;
  startAssistantMessage: () => string;
  appendStreamToken: (token: string) => void;
  finalizeStream: (fullText: string, isIntermediate?: boolean) => void;
  addToolCall: (tool: string, args: Record<string, unknown>) => void;
  updateToolResult: (tool: string, result: string, success: boolean) => void;
  addToolOutput: (message: string) => void;
  addErrorMessage: (message: string) => void;
  clearChat: () => void;
}

let msgIdCounter = 0;
function nextId(): string {
  return `msg-${Date.now()}-${++msgIdCounter}`;
}

// Token buffer: accumulate tokens and flush at 50ms intervals to reduce renders
let tokenBuffer = "";
let flushTimer: ReturnType<typeof setTimeout> | null = null;

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  streamingText: "",
  currentAssistantId: null,

  addUserMessage(text) {
    const msg: ChatMessage = {
      id: nextId(),
      role: "user",
      blocks: [{ type: "text", content: text }],
      timestamp: Date.now(),
    };
    set((s) => ({ messages: [...s.messages, msg] }));
  },

  startAssistantMessage() {
    const id = nextId();
    const msg: ChatMessage = {
      id,
      role: "assistant",
      blocks: [],
      timestamp: Date.now(),
    };
    set((s) => ({
      messages: [...s.messages, msg],
      isStreaming: true,
      streamingText: "",
      currentAssistantId: id,
    }));
    return id;
  },

  appendStreamToken(token) {
    tokenBuffer += token;
    if (!flushTimer) {
      flushTimer = setTimeout(() => {
        const buffered = tokenBuffer;
        tokenBuffer = "";
        flushTimer = null;
        if (buffered) {
          set((s) => ({ streamingText: s.streamingText + buffered }));
        }
      }, 50);
    }
  },

  finalizeStream(fullText, isIntermediate = false) {
    // Flush any remaining buffered tokens
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    tokenBuffer = "";

    const { currentAssistantId, messages } = get();
    if (!currentAssistantId) return;

    const trimmed = fullText.trim();
    // Only add a text block if there's actual content
    const newBlocks = trimmed
      ? [...(messages.find((m) => m.id === currentAssistantId)?.blocks || []), { type: "text" as const, content: trimmed }]
      : [...(messages.find((m) => m.id === currentAssistantId)?.blocks || [])];

    if (isIntermediate) {
      // Intermediate finalize during tool call round: keep streaming state alive
      // so the next stream/token can append to the same assistant message
      set({
        messages: messages.map((m) =>
          m.id === currentAssistantId ? { ...m, blocks: newBlocks } : m
        ),
        streamingText: "",
        // Keep isStreaming=true and currentAssistantId set so next round continues in same message
      });
    } else {
      set({
        messages: messages.map((m) =>
          m.id === currentAssistantId ? { ...m, blocks: newBlocks } : m
        ),
        isStreaming: false,
        streamingText: "",
        currentAssistantId: null,
      });
    }
  },

  addToolCall(tool, args) {
    const { currentAssistantId, messages } = get();
    const targetId = currentAssistantId ?? messages.at(-1)?.id;
    if (!targetId) return;

    set({
      messages: messages.map((m) =>
        m.id === targetId
          ? {
              ...m,
              blocks: [
                ...m.blocks,
                {
                  type: "tool_call" as const,
                  tool,
                  args,
                  status: "running" as const,
                },
              ],
            }
          : m,
      ),
    });
  },

  updateToolResult(tool, result, success) {
    set((s) => ({
      messages: s.messages.map((m) => ({
        ...m,
        blocks: m.blocks.map((b) =>
          b.type === "tool_call" && b.tool === tool && b.status === "running"
            ? { ...b, result, status: success ? ("done" as const) : ("error" as const) }
            : b,
        ),
      })),
    }));
  },

  addToolOutput(message) {
    const { currentAssistantId, messages } = get();
    const targetId = currentAssistantId ?? messages.at(-1)?.id;
    if (!targetId) return;
    set({
      messages: messages.map((m) =>
        m.id === targetId
          ? { ...m, blocks: [...m.blocks, { type: "tool_output" as const, content: message }] }
          : m
      ),
    });
  },

  addErrorMessage(message) {
    const { messages } = get();
    const errMsg: ChatMessage = {
      id: nextId(),
      role: "assistant",
      blocks: [{ type: "error", content: message }],
      timestamp: Date.now(),
    };
    set({ messages: [...messages, errMsg] });
  },

  clearChat() {
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    tokenBuffer = "";
    set({
      messages: [],
      isStreaming: false,
      streamingText: "",
      currentAssistantId: null,
    });
  },
}));
