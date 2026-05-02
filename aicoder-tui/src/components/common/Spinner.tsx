import { Text } from "ink";
import Spinner from "ink-spinner";

const VERBS = [
  "Thinking...",
  "Pondering...",
  "Musing...",
  "Contemplating...",
  "Reasoning...",
  "Analyzing...",
  "Processing...",
  "Generating...",
];

let verbIndex = 0;

function nextVerb(): string {
  return VERBS[verbIndex++ % VERBS.length];
}

interface Props {
  text?: string;
}

export function WhimsicalSpinner({ text }: Props) {
  const label = text ?? nextVerb();
  return (
    <Text>
      <Text color="#9fcaff">
        <Spinner type="dots" />
      </Text>
      {" "}
      <Text dimColor>{label}</Text>
    </Text>
  );
}
