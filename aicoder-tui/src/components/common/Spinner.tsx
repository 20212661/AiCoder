import { Text } from "../../ink/index.js";

interface Props {
  text?: string;
}

export function WhimsicalSpinner({ text }: Props) {
  return (
    <Text>
      <Text color="#9fcaff">{"⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"}</Text>
      {" "}
      <Text dim>{text ?? "thinking"}</Text>
    </Text>
  );
}
