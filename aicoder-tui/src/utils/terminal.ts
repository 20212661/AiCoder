export function getTerminalWidth(): number {
  return process.stdout.columns || 80;
}

export function getTerminalHeight(): number {
  return process.stdout.rows || 24;
}

export function supportsTrueColor(): boolean {
  const term = process.env.TERM ?? "";
  const colorterm = process.env.COLORTERM ?? "";
  return colorterm.includes("truecolor") || colorterm.includes("24bit") ||
    term.includes("256color");
}
