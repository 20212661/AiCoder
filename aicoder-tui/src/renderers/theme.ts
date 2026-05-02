export interface Theme {
  name: string;
  colors: {
    primary: string;
    secondary: string;
    accent: string;
    background: string;
    surface: string;
    text: string;
    textDim: string;
    userBubble: string;
    aiBubble: string;
    thinking: string;
    toolCall: string;
    error: string;
    success: string;
    warning: string;
    diffAdd: string;
    diffRemove: string;
    border: string;
    borderFocus: string;
  };
  borderStyle: "single" | "double" | "round" | "bold";
}

import chalk from "chalk";

export const darkTheme: Theme = {
  name: "dark",
  colors: {
    primary: "#61dafb",
    secondary: "#888",
    accent: "#e10098",
    background: "#1a1a2e",
    surface: "#16213e",
    text: "#e0e0e0",
    textDim: "#666",
    userBubble: "#1a3a5c",
    aiBubble: "#2a1a3e",
    thinking: "#ffd700",
    toolCall: "#00d4aa",
    error: "#ff4444",
    success: "#00ff88",
    warning: "#ffaa00",
    diffAdd: "#22c55e",
    diffRemove: "#ef4444",
    border: "#333",
    borderFocus: "#61dafb",
  },
  borderStyle: "round",
};

export const lightTheme: Theme = {
  name: "light",
  colors: {
    primary: "#0066cc",
    secondary: "#999",
    accent: "#cc0066",
    background: "#ffffff",
    surface: "#f5f5f5",
    text: "#1a1a1a",
    textDim: "#999",
    userBubble: "#e3f2fd",
    aiBubble: "#f3e5f5",
    thinking: "#ff8f00",
    toolCall: "#00897b",
    error: "#d32f2f",
    success: "#2e7d32",
    warning: "#f57c00",
    diffAdd: "#2e7d32",
    diffRemove: "#c62828",
    border: "#ccc",
    borderFocus: "#0066cc",
  },
  borderStyle: "single",
};

export const opencodeTheme: Theme = {
  name: "opencode",
  colors: {
    primary: "#9fcaff",
    secondary: "#5c6773",
    accent: "#ffc080",
    background: "#101419",
    surface: "#1a1f28",
    text: "#d4d4d4",
    textDim: "#5c6773",
    userBubble: "#1a2a3a",
    aiBubble: "#1a2832",
    thinking: "#ffc080",
    toolCall: "#9fcaff",
    error: "#ff6b6b",
    success: "#7ec699",
    warning: "#e6b450",
    diffAdd: "#7ec699",
    diffRemove: "#ff6b6b",
    border: "#2a3040",
    borderFocus: "#9fcaff",
  },
  borderStyle: "single",
};

const themes: Record<string, Theme> = {
  dark: darkTheme,
  light: lightTheme,
  opencode: opencodeTheme,
};

export function getTheme(name: string): Theme {
  return themes[name] ?? darkTheme;
}

export function c(hex: string): typeof chalk {
  return chalk.hex(hex);
}
