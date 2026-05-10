#!/usr/bin/env node
// aicoder CLI entry point
// On Windows, ensure User-level env vars (API keys) are visible to child processes
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

// Sync missing API keys from Windows User environment into process.env
// This fixes the issue where Git Bash / VSCode terminal doesn't load User env vars
if (process.platform === "win32") {
  const apiKeys = [
    "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY",
  ];
  for (const key of apiKeys) {
    if (!process.env[key]) {
      try {
        const val = execSync(
          `powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('${key}','User')"`,
          { encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] }
        ).trim();
        if (val) process.env[key] = val;
      } catch {}
    }
  }
}

const __dirname = dirname(fileURLToPath(import.meta.url));
const distPath = resolve(__dirname, "..", "dist", "index.js");

// Windows ESM requires file:// URL for dynamic import
import(pathToFileURL(distPath).href);
