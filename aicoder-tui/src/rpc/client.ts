import { EventEmitter } from "node:events";
import { StdioTransport } from "./transport.js";
import type {
  JsonRpcRequest,
  JsonRpcResponse,
  JsonRpcNotification,
  NotificationMethod,
  BackendNotifications,
} from "./protocol.js";

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class RpcClient extends EventEmitter {
  private transport = new StdioTransport();
  private idCounter = 0;
  private pending = new Map<number, PendingRequest>();

  async connect(
    command?: string,
    args?: string[],
  ): Promise<void> {
    this.transport.on("message", (msg) => this.handleMessage(msg));
    this.transport.on("stderr", (data) => this.emit("stderr", data));
    this.transport.on("close", (code) => this.emit("close", code));
    this.transport.on("error", (err) => this.emit("error", err));

    await this.transport.connect(command, args);
    this.emit("connected");
  }

  async request<T = unknown>(
    method: string,
    params?: unknown,
    timeout = 30000,
  ): Promise<T> {
    const id = ++this.idCounter;
    const msg: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };

    return new Promise<T>((resolve, reject) => {
      if (!this.connected) {
        reject(new Error("Cannot send: transport disconnected"));
        return;
      }

      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`RPC timeout after ${timeout}ms: ${method}`));
      }, timeout);

      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      });

      this.transport.send(JSON.stringify(msg));
    });
  }

  notify(method: string, params?: unknown): void {
    if (!this.connected) return;
    const msg: JsonRpcNotification = { jsonrpc: "2.0", method, params };
    this.transport.send(JSON.stringify(msg));
  }

  onNotification<K extends NotificationMethod>(
    method: K,
    handler: (params: BackendNotifications[K]) => void,
  ): void {
    this.on(method, handler);
  }

  private handleMessage(msg: JsonRpcResponse | JsonRpcNotification): void {
    if ("id" in msg && this.pending.has(msg.id)) {
      const pending = this.pending.get(msg.id)!;
      clearTimeout(pending.timer);
      this.pending.delete(msg.id);

      if (msg.error) {
        pending.reject(new Error(msg.error.message));
      } else {
        pending.resolve(msg.result);
      }
    } else if ("method" in msg) {
      this.emit(msg.method, msg.params);
    }
  }

  async disconnect(): Promise<void> {
    for (const [, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error("Transport disconnected"));
    }
    this.pending.clear();
    await this.transport.disconnect();
    this.emit("disconnected");
  }

  get connected(): boolean {
    return this.transport.connected;
  }
}
