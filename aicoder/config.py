"""Configuration management with pydantic validation and priority chain.

Priority: CLI args > environment variables > config file > defaults.
"""
import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .exceptions import ConfigError

DEFAULT_CONFIG_DIR = Path.home() / ".aicoder"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "settings.json"


class EnvConfig(BaseModel):
    """Environment variables to inject at startup."""

    DEEPSEEK_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    COHERE_API_KEY: str | None = None
    TOGETHER_API_KEY: str | None = None
    MISTRAL_API_KEY: str | None = None
    PERPLEXITY_API_KEY: str | None = None

    model_config = {"extra": "allow"}


class ModelOverrides(BaseModel):
    """Per-model configuration overrides."""

    edit_format: str | None = None
    map_tokens: int | None = None
    stream: bool | None = None

    model_config = {"extra": "allow"}


class Settings(BaseModel):
    """Root configuration schema for ~/.aicoder/settings.json."""

    env: EnvConfig = Field(default_factory=EnvConfig)
    default_model: str = "deepseek/deepseek-chat"
    default_edit_format: str = "whole"
    auto_commits: bool = True
    map_tokens: int = 1024
    stream: bool = True
    verbose: bool = False
    model_overrides: dict[str, ModelOverrides] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


CONFIG_TEMPLATE = """\
{
  "env": {
    "DEEPSEEK_API_KEY": "sk-your-key-here",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": ""
  },
  "default_model": "deepseek/deepseek-chat",
  "default_edit_format": "whole",
  "auto_commits": true,
  "map_tokens": 1024,
  "stream": true,
  "verbose": false,
  "model_overrides": {}
}
"""


def resolve_config_path(cli_path: str | None = None) -> Path:
    """Resolve config file path with priority: CLI > env var > default."""
    if cli_path:
        return Path(cli_path)
    env_path = os.environ.get("AICODER_CONFIG")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_PATH


def load_settings(config_path: str | None = None) -> Settings:
    """Load and validate settings from config file.

    Returns a validated Settings instance. If the config file doesn't exist,
    returns default settings. Environment variables are applied on top via
    `apply_env_vars()`.
    """
    path = resolve_config_path(config_path)

    if not path.is_file():
        return Settings()

    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as err:
        raise ConfigError(f"Failed to load config {path}: {err}") from err

    try:
        settings = Settings.model_validate(raw)
    except ValidationError as err:
        raise ConfigError(f"Invalid config {path}: {err}") from err

    return settings


def apply_env_vars(settings: Settings) -> None:
    """Apply settings.env values to os.environ (only if not already set)."""
    env_data = settings.env.model_dump(exclude_none=True)
    for key, value in env_data.items():
        os.environ.setdefault(key, str(value))


def init_config(path: str | None = None) -> Path:
    """Generate a config template file.

    Returns the path to the created file.
    """
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    if target.exists():
        raise ConfigError(f"Config file already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return target
