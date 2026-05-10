import { Box, Text } from "../../ink/index.js";
import { renderInlineMarkdown } from "../../renderers/markdown.js";

interface Props {
  content: string;
}

type PlanSections = {
  plan: string[];
  findings: string[];
  nextStep: string[];
  notes: string[];
};

export function PlanBlock({ content }: Props) {
  const sections = parsePlanSections(content);

  return (
    <Box flexDirection="column" marginY={1}>
      <Text color="claude" bold>[ Plan ]</Text>
      <Text dimColor>{"-".repeat(72)}</Text>
      <Section title="Plan" items={sections.plan} />
      <Section title="Findings" items={sections.findings} />
      <Section title="Next step" items={sections.nextStep} />
      {sections.notes.length > 0 ? <Section title="Notes" items={sections.notes} /> : null}
      <Text dimColor>{"Use /act to execute when you're ready."}</Text>
    </Box>
  );
}

function Section({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text bold>{title}</Text>
      {items.map((item, index) => (
        <Text key={`${title}-${index}`}>  {renderInlineMarkdown(item)}</Text>
      ))}
    </Box>
  );
}

function parsePlanSections(content: string): PlanSections {
  const sections: PlanSections = {
    plan: [],
    findings: [],
    nextStep: [],
    notes: [],
  };

  let current: keyof PlanSections = "notes";
  const lines = content.split("\n").map((line) => line.trim()).filter(Boolean);

  for (const line of lines) {
    const lower = line.toLowerCase();
    if (lower === "plan:" || lower === "plan") {
      current = "plan";
      continue;
    }
    if (lower === "findings:" || lower === "findings") {
      current = "findings";
      continue;
    }
    if (lower === "next step:" || lower === "next step") {
      current = "nextStep";
      continue;
    }

    sections[current].push(normalizePlanLine(line));
  }

  return sections;
}

function normalizePlanLine(line: string): string {
  return line
    .replace(/^\d+\.\s*/, "")
    .replace(/^[-*]\s*/, "");
}

export function looksLikePlanContent(content: string): boolean {
  const lower = content.toLowerCase();
  return lower.includes("plan:") && (lower.includes("findings:") || lower.includes("next step:"));
}
