#!/usr/bin/env node
import { render } from "ink";
import { App } from "./App.js";

async function main() {
  const { waitUntilExit } = render(<App />);
  await waitUntilExit();
  process.exit(0);
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
