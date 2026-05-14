#!/usr/bin/env node

async function main() {
  const mod = await import("./official-ink/index.js");
  // official-ink/index.tsx exports waitUntilExit via render()
  // The module starts the Ink app and calls waitUntilExit internally,
  // so the import resolves when the app exits.
  if (mod.waitUntilExit) {
    await mod.waitUntilExit();
  }
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
