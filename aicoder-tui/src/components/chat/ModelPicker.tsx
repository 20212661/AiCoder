import { Box, Text } from "../../ink/index.js";

interface ModelPickerProps {
  currentModel: string;
  error: string;
  loading: boolean;
  models: string[];
  selectedIndex: number;
  visible: boolean;
}

const PAGE_SIZE = 8;

type ModelMeta = {
  label: string;
  summary: string;
};

function prettifyModelName(model: string): string {
  return model
    .split("-")
    .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : part))
    .join(" ");
}

function getModelMeta(model: string): ModelMeta {
  const lower = model.toLowerCase();

  if (lower === "machao-flash") {
    return {
      label: "Default (recommended)",
      summary: "Balanced default for most coding sessions.",
    };
  }

  if (lower === "machao-pro") {
    return {
      label: "Machao Pro",
      summary: "Stronger reasoning for complex planning and architecture.",
    };
  }

  if (lower.includes("gpt-4o")) {
    return {
      label: prettifyModelName(model),
      summary: "Fast multimodal GPT-4o family model.",
    };
  }

  if (lower.includes("gpt-4")) {
    return {
      label: prettifyModelName(model),
      summary: "General-purpose GPT-4 family model for coding tasks.",
    };
  }

  if (lower.includes("claude") && lower.includes("haiku")) {
    return {
      label: "Haiku",
      summary: "Fastest Claude-family option for lightweight requests.",
    };
  }

  if (lower.includes("claude") && lower.includes("opus")) {
    return {
      label: "Opus",
      summary: "Most capable Claude-family option for deep analysis.",
    };
  }

  if (lower.includes("claude") && lower.includes("sonnet")) {
    return {
      label: "Sonnet",
      summary: "Balanced Claude-family option for longer coding sessions.",
    };
  }

  if (lower.includes("deepseek") && lower.includes("reasoner")) {
    return {
      label: "DeepSeek Reasoner",
      summary: "Reasoning-focused model suited to deliberate problem solving.",
    };
  }

  if (lower.includes("deepseek")) {
    return {
      label: prettifyModelName(model),
      summary: "DeepSeek family model optimized for code and chat workflows.",
    };
  }

  if (lower.includes("gemini")) {
    return {
      label: prettifyModelName(model),
      summary: "Gemini family model with long-context support.",
    };
  }

  if (lower.includes("llama")) {
    return {
      label: prettifyModelName(model),
      summary: "Open-weight Llama family model for general code assistance.",
    };
  }

  if (lower === "o1" || lower === "o1-mini" || lower === "o3-mini") {
    return {
      label: prettifyModelName(model),
      summary: "Reasoning-oriented OpenAI model variant.",
    };
  }

  return {
    label: prettifyModelName(model),
    summary: "Available model for this session.",
  };
}

function truncate(text: string, max = 64): string {
  return text.length > max ? `${text.slice(0, max - 3)}...` : text;
}

export function getModelPickerPageSize() {
  return PAGE_SIZE;
}

export function ModelPicker({
  currentModel,
  error,
  loading,
  models,
  selectedIndex,
  visible,
}: ModelPickerProps) {
  if (!visible) return null;

  const pageCount = Math.max(1, Math.ceil(models.length / PAGE_SIZE));
  const currentPage = Math.floor(selectedIndex / PAGE_SIZE);
  const pageStart = currentPage * PAGE_SIZE;
  const pageItems = models.slice(pageStart, pageStart + PAGE_SIZE);
  const selectedModel = models[selectedIndex] ?? "";
  const selectedMeta = selectedModel ? getModelMeta(selectedModel) : null;

  return (
    <Box flexDirection="column" marginLeft={2} marginBottom={1}>
      <Text bold>Select model</Text>
      <Text dimColor>
        Switch between available models. Applies to this session immediately.
      </Text>

      {loading ? <Text dimColor>Loading models...</Text> : null}
      {error ? <Text color="error">{error}</Text> : null}
      {!loading && !error && models.length === 0 ? (
        <Text dimColor>No models available.</Text>
      ) : null}

      {!loading && !error && pageItems.length > 0 ? (
        <Box flexDirection="column" marginTop={1}>
          {pageItems.map((model, offset) => {
            const absoluteIndex = pageStart + offset;
            const isSelected = absoluteIndex === selectedIndex;
            const isCurrent = model === currentModel;
            const meta = getModelMeta(model);

            return (
              <Box key={model}>
                <Text>{isSelected ? ">" : " "} </Text>
                <Text dimColor>{absoluteIndex + 1}. </Text>
                <Text color={isSelected ? "claude" : undefined} bold={isSelected}>
                  {meta.label}
                </Text>
                {isCurrent ? <Text color="success"> {" [current]"}</Text> : null}
                <Text dimColor>{"  "}{truncate(meta.summary)}</Text>
              </Box>
            );
          })}
        </Box>
      ) : null}

      {!loading && !error && selectedMeta ? (
        <Box flexDirection="column" marginTop={1}>
          <Text bold>{selectedMeta.label}</Text>
          <Text dimColor>{selectedModel}</Text>
          <Text>{selectedMeta.summary}</Text>
        </Box>
      ) : null}

      {!loading && !error && models.length > PAGE_SIZE ? (
        <Text dimColor>
          Page {currentPage + 1}/{pageCount}  Left/Right switch pages
        </Text>
      ) : null}
      <Text dimColor>Up/Down move  Enter confirm  Esc close</Text>
    </Box>
  );
}
