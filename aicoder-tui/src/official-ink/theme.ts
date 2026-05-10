export const theme = {
  colors: {
    primary: "cyan",
    secondary: "gray",
    success: "green",
    error: "red",
    warning: "yellow",
    info: "blue",
    plan: "magenta",
    act: "cyan",
    user: "green",
    assistant: "white",
    tool: "yellow",
    dim: "gray",
  },
} as const;

export type ThemeColor = (typeof theme.colors)[keyof typeof theme.colors];
