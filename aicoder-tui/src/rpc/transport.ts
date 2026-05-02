import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import type { JsonRpcResponse, JsonRpcNotification } from "./protocol.js";

export class StdioTransport extends EventEmitter {
  private proc: ChildProcess | null = null;
  private buffer = "";

  async connect(
    command: string = "python",
    args: string[] = ["-m", "aicoder", "--serve"],
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      this.proc = spawn(command, args, {
        stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env },
      });

      this.proc.on("error", (err) => {
        reject(err);
        this.emit("error", err);
      });

      this.proc.stdout!.on("data", (data: Buffer) => {
        this.buffer += data.toString();
        this.processBuffer();
      });

      this.proc.stderr!.on("data", (data: Buffer) => {
        this.emit("stderr", data.toString());
      });

      this.proc.on("close", (code) => {
        this.proc = null;
        this.emit("close", code);
      });

      // Wait a tick to confirm process started
      setImmediate(() => resolve());
    });
  }

  send(data: string): void {
    if (!this.proc?.stdin?.writable) {
      throw new Error("Transport not connected");
    }
    this.proc.stdin.write(data + "\n");
  }

  private processBuffer(): void {
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop()!;

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line) as
          | JsonRpcResponse
          | JsonRpcNotification;
        this.emit("message", msg);
      } catch {
        this.emit("raw", line);
      }
    }
  }

  async disconnect(): Promise<void> {
    if (this.proc) {
      this.proc.kill("SIGTERM");
      this.proc = null;
    }
  }

  get connected(): boolean {
    return this.proc !== null && !this.proc.killed;
  }
}
