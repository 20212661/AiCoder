export { renderCodeBlock, renderDiff, renderInlineMarkdown } from "./markdown.js";

export function renderToolOutput(tool: string, output: string): string {
  const prefix = `┌─ ${tool} ─`;
  const border = "─".repeat(Math.max(0, 40 - prefix.length));
  const header = prefix + border + "┐";

  return [
    header,
    ...output.split("\n").map((l) => `│ ${l}`),
    `└${"─".repeat(header.length - 1)}┘`,
  ].join("\n");
}
