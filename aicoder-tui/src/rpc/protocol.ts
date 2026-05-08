// JSON-RPC 2.0 protocol types

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: unknown;
}

export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: string;
  params?: unknown;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: JsonRpcError;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

// Backend → TUI notifications
export interface BackendNotifications {
  "stream/token": { text: string };
  "stream/finalize": { text: string };
  "assistant/output": { text: string };
  "tool/call_started": { tool: string; args: Record<string, unknown> };
  "tool/call_finished": { tool: string; result: string; success: boolean };
  "tool/output": { message: string };
  "tool/error": { message: string };
  "approval/request": { id: string; question: string; diff?: string };
  "confirm/ask": { id: string; question: string };
  "input/request": {
    root: string;
    commands?: string[];
    inchat_files?: string[];
    addable_files?: string[];
  };
  "status/update": {
    model?: string;
    tokens?: number;
    cost?: number;
    planMode?: boolean;
    mode?: "plan" | "act";
    yolo?: boolean;
    phase?: string;
  };
}

// TUI → Backend requests
export interface BackendRequests {
  "approval/respond": { id: string; approved: boolean };
  "confirm/respond": { id: string; confirmed: boolean };
  "input/submit": { text: string };
  "cancel/generation": {};
  "model/list": {};
  "session/list": {};
  "session/resume": { id: string };
  "session/new": {};
}

export type NotificationMethod = keyof BackendNotifications;
export type RequestMethod = keyof BackendRequests;
