import chalk from "chalk";

export function renderDiffLines(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      if (line.startsWith("+++ ") || line.startsWith("--- "))
        return chalk.bold.white(line);
      if (line.startsWith("+"))
        return chalk.green(line);
      if (line.startsWith("-"))
        return chalk.red(line);
      if (line.startsWith("@@"))
        return chalk.blue(line);
      return chalk.dim(line);
    })
    .join("\n");
}
