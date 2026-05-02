import { Text } from "ink";

interface Props {
  label: string;
  color?: string;
}

export function Badge({ label, color = "cyan" }: Props) {
  return <Text color={color}>[{label}]</Text>;
}
