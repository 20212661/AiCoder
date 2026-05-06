import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { JsonRpcResponse, JsonRpcNotification } from "./protocol.js";

// src/rpc/transport.ts → aicoder-tui/src/rpc/ → aicoder-tui/ → aiCoder/ (project root with aicoder/ Python package)
const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..", "..", "..");

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
        cwd: projectRoot,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      });

      let settled = false;

      this.proc.on("error", (err) => {
        if (!settled) { settled = true; reject(err); }
        this.emit("error", err);
      });

      this.proc.on("exit", (code) => {
        if (!settled && code !== null && code !== 0) {
          settled = true;
          reject(new Error(`Python process exited with code ${code}`));
        }
      });

      this.proc.stdout!.on("data", (data: Buffer) => {
        this.buffer += data.toString();
        this.processBuffer();
      });

      this.proc.stderr!.on("data", (data: Buffer) => {
        this.emit("stderr", data.toString());
      });

      this.proc.on("close", (code) => {
        if (!settled) {
          settled = true;
          reject(new Error(`Python process closed unexpectedly with code ${code}`));
        }
        this.proc = null;
        // Don't emit "close" if we already rejected
        if (code !== null) {
          this.emit("close", code);
        }
      });

      // Wait for first stdout data or a short timeout
      const onFirstData = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      this.proc.stdout!.once("data", onFirstData);

      // Fallback timeout: resolve anyway after 5s so the UI can show errors
      setTimeout(() => {
        if (!settled) {
          settled = true;
          resolve();
        }
      }, 5000);
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
