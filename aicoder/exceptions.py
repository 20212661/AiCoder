"""Project-level exception hierarchy."""


class AiCoderError(Exception):
    """Base exception for all AiCoder errors."""


class ConfigError(AiCoderError):
    """Raised for invalid configuration (missing API keys, malformed JSON, etc.)."""


class LLMError(AiCoderError):
    """Raised when the LLM API call fails after all retries are exhausted."""

    def __init__(self, model: str, message: str):
        self.model = model
        super().__init__(f"[{model}] {message}")


class ToolError(AiCoderError):
    """Raised for tool execution failures."""
