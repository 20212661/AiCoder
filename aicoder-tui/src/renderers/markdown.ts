import chalk from "chalk";
import { highlight } from "cli-highlight";

export function renderCodeBlock(code: string, language?: string): string {
  try {
    return highlight(code.trim(), {
      language: language || "plaintext",
      theme: {
        keyword: chalk.hex("#c678dd"),
        built_in: chalk.hex("#e5c07b"),
        type: chalk.hex("#e5c07b"),
        literal: chalk.hex("#d19a66"),
        number: chalk.hex("#d19a66"),
        regexp: chalk.hex("#98c379"),
        string: chalk.hex("#98c379"),
        subst: chalk.hex("#e06c75"),
        symbol: chalk.hex("#61afef"),
        class: chalk.hex("#e5c07b").bold,
        function: chalk.hex("#61afef"),
        title: chalk.hex("#61afef"),
        params: chalk.hex("#abb2bf"),
        comment: chalk.hex("#5c6370").italic,
        doctag: chalk.hex("#c678dd"),
        meta: chalk.hex("#61afef"),
        section: chalk.hex("#e06c75"),
        tag: chalk.hex("#e06c75"),
        name: chalk.hex("#e06c75"),
        attr: chalk.hex("#d19a66"),
        attribute: chalk.hex("#98c379"),
        variable: chalk.hex("#e06c75"),
        bullet: chalk.hex("#61afef"),
        code: chalk.hex("#98c379"),
        emphasis: chalk.italic,
        strong: chalk.bold,
        formula: chalk.hex("#abb2bf"),
        addition: chalk.hex("#98c379"),
        deletion: chalk.hex("#e06c75"),
      },
    });
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
