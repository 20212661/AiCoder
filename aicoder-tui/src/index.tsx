#!/usr/bin/env node
import React from "react";
import { renderSync } from "./ink/root.js";
import { ThemeProvider } from "./design-system/ThemeProvider.js";
import { App } from "./App.js";

async function main() {
  const { waitUntilExit } = renderSync(
    React.createElement(ThemeProvider, null, React.createElement(App)),
    {
      exitOnCtrlC: false,
      patchConsole: true,
    },
  );
  await waitUntilExit();
  process.exit(0);
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
