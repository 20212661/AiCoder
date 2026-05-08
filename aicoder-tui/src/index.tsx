#!/usr/bin/env node

async function main() {
  // Default: official Ink TUI
  // Fallback: set AICODER_TUI_RUNTIME=legacy to use old renderer
  if (process.env.AICODER_TUI_RUNTIME === "legacy") {
    const React = await import("react");
    const { renderSync } = await import("./ink/root.js");
    const { ThemeProvider } = await import("./design-system/ThemeProvider.js");
    const { App } = await import("./App.js");

    const { waitUntilExit } = renderSync(
      React.createElement(ThemeProvider, null, React.createElement(App)),
      {
        exitOnCtrlC: false,
        patchConsole: true,
      },
    );
    await waitUntilExit();
  } else {
    const mod = await import("./official-ink/index.js");
    // official-ink/index.tsx exports waitUntilExit via render()
    // The module starts the Ink app and calls waitUntilExit internally,
    // so the import resolves when the app exits.
    if (mod.waitUntilExit) {
      await mod.waitUntilExit();
    }
  }
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
