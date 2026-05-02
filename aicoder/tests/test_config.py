"""Unit tests for config.py — settings loading, validation, env vars."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from aicoder.config import (
    Settings,
    EnvConfig,
    ModelOverrides,
    resolve_config_path,
    load_settings,
    apply_env_vars,
    init_config,
    CONFIG_TEMPLATE,
    DEFAULT_CONFIG_PATH,
)
from aicoder.exceptions import ConfigError


class TestEnvConfig:
    def test_defaults(self):
        e = EnvConfig()
        assert e.DEEPSEEK_API_KEY is None
        assert e.OPENAI_API_KEY is None

    def test_extra_allow(self):
        e = EnvConfig(CUSTOM_VAR="value")
        assert e.CUSTOM_VAR == "value"  # type: ignore


class TestModelOverrides:
    def test_defaults(self):
        m = ModelOverrides()
        assert m.edit_format is None
        assert m.map_tokens is None


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert s.default_model == "deepseek/deepseek-chat"
        assert s.auto_commits is True
        assert s.stream is True
        assert s.verbose is False
        assert s.map_tokens == 1024

    def test_from_dict(self):
        s = Settings.model_validate({
            "default_model": "gpt-4o",
            "auto_commits": False,
        })
        assert s.default_model == "gpt-4o"
        assert s.auto_commits is False


class TestResolveConfigPath:
    def test_cli_path(self):
        assert resolve_config_path("/custom/path.json") == Path("/custom/path.json")

    def test_env_var(self):
        with patch.dict(os.environ, {"AICODER_CONFIG": "/env/path.json"}):
            assert resolve_config_path() == Path("/env/path.json")

    def test_default(self):
        with patch.dict(os.environ, {}, clear=True):
            path = resolve_config_path()
            assert path == DEFAULT_CONFIG_PATH


class TestLoadSettings:
    def test_missing_file_returns_defaults(self, tmp_path):
        s = load_settings(str(tmp_path / "nonexistent.json"))
        assert s.default_model == "deepseek/deepseek-chat"

    def test_valid_file(self, tmp_path):
        config = tmp_path / "settings.json"
        config.write_text(json.dumps({"default_model": "gpt-4o", "auto_commits": False}))
        s = load_settings(str(config))
        assert s.default_model == "gpt-4o"
        assert s.auto_commits is False

    def test_invalid_json(self, tmp_path):
        config = tmp_path / "bad.json"
        config.write_text("{invalid json")
        with pytest.raises(ConfigError, match="Failed to load config"):
            load_settings(str(config))

    def test_invalid_schema(self, tmp_path):
        config = tmp_path / "bad_schema.json"
        config.write_text(json.dumps({"auto_commits": "not_a_bool"}))
        with pytest.raises(ConfigError, match="Invalid config"):
            load_settings(str(config))


class TestApplyEnvVars:
    def test_sets_unset_vars(self):
        s = Settings(env=EnvConfig(CUSTOM_TEST_VAR_123="hello"))
        os.environ.pop("CUSTOM_TEST_VAR_123", None)
        apply_env_vars(s)
        assert os.environ.get("CUSTOM_TEST_VAR_123") == "hello"
        del os.environ["CUSTOM_TEST_VAR_123"]

    def test_does_not_override_existing(self):
        os.environ["CUSTOM_TEST_VAR_456"] = "original"
        s = Settings(env=EnvConfig(CUSTOM_TEST_VAR_456="new"))
        apply_env_vars(s)
        assert os.environ["CUSTOM_TEST_VAR_456"] == "original"
        del os.environ["CUSTOM_TEST_VAR_456"]

    def test_skips_none_values(self):
        s = Settings(env=EnvConfig(DEEPSEEK_API_KEY=None))
        keys_before = set(os.environ.keys())
        apply_env_vars(s)
        # Should not have added DEEPSEEK_API_KEY if it wasn't set
        if "DEEPSEEK_API_KEY" not in keys_before:
            assert "DEEPSEEK_API_KEY" not in os.environ or os.environ["DEEPSEEK_API_KEY"] == ""


class TestInitConfig:
    def test_creates_file(self, tmp_path):
        target = tmp_path / "settings.json"
        result = init_config(str(target))
        assert result == target
        assert target.exists()
        content = json.loads(target.read_text())
        assert "default_model" in content

    def test_refuses_existing(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text("{}")
        with pytest.raises(ConfigError, match="already exists"):
            init_config(str(target))
