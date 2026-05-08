import { Box, Text } from "../../ink/index.js";
import { renderInlineMarkdown } from "../../renderers/markdown.js";
import { useConfigStore } from "../../stores/configStore.js";

interface Props {
  content: string;
}

export function TextBlock({ content }: Props) {
  const planMode = useConfigStore((s) => s.planMode);
  const lines = sanitizeText(content, planMode).split("\n").filter((line) => line.length > 0);
  if (lines.length === 0) return null;
  return (
    <Box flexDirection="column">
      {lines.map((line, i) => (
        <Text key={i}>{renderInlineMarkdown(line)}</Text>
      ))}
    </Box>
  );
}

export function sanitizeText(content: string, planMode: boolean): string {
  if (!planMode) return content;

  const filtered = content
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      if (!trimmed) return false;
      if (trimmed.startsWith("<") && trimmed.endsWith(">")) return false;
      if (trimmed.startsWith("Let me ")) return false;
      if (trimmed.startsWith("Now let me ")) return false;
      if (trimmed.startsWith("First, let me ")) return false;
      return true;
    });

  return filtered.join("\n");
}
