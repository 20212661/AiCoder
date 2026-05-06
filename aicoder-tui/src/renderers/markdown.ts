import chalk from "chalk";
import hljs from "highlight.js";

export function renderCodeBlock(code: string, language?: string): string {
  try {
    let result: string;
    if (language && hljs.getLanguage(language)) {
      result = hljs.highlight(code.trim(), { language }).value;
    } else {
      result = hljs.highlightAuto(code.trim()).value;
    }
    return result;
  } catch {
    return code;
  }
}

export function renderInlineMarkdown(text: string): string {
  let result = text;

  // Inline code
  result = result.replace(
    /`([^`]+)`/g,
    (_, code) => chalk.hex("#98c379")(code),
  );

  // Bold
  result = result.replace(
    /\*\*([^*]+)\*\*/g,
    (_, t) => chalk.bold(t),
  );

  // Italic
  result = result.replace(
    /(?<!\*)\*([^*]+)\*(?!\*)/g,
    (_, t) => chalk.italic(t),
  );

  // Links
  result = result.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_, label, _url) => chalk.hex("#61afeb").underline(label),
  );

  return result;
}

export function renderDiff(diffText: string): string {
  return diffText
    .split("\n")
    .map((line) => {
      if (line.startsWith("+++ ") || line.startsWith("--- "))
        return chalk.bold(line);
      if (line.startsWith("+"))
        return chalk.hex("#98c379")(line);
      if (line.startsWith("-"))
        return chalk.hex("#e06c75")(line);
      if (line.startsWith("@@"))
        return chalk.hex("#61afeb")(line);
      return line;
    })
    .join("\n");
}
