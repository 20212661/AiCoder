"""Unit tests for models.py — model registry, resolution, capabilities."""
import pytest
from aicoder.models import (
    Model,
    ModelCapabilities,
    _resolve_model_limits,
    _resolve_model_capabilities,
    _load_models,
    reload_models,
    DEFAULT_MODEL_NAME,
    DEFAULT_TOKEN_LIMITS,
    CONTEXT_SAFETY_MARGIN,
    MODEL_TOKEN_LIMITS,
    MACHO_BACKEND_MAP,
)


@pytest.fixture(autouse=True)
def _fresh_models():
    reload_models()
    yield
    reload_models()


class TestResolveModelLimits:
    def test_exact_match(self):
        result = _resolve_model_limits("gpt-4o")
        assert result["max_input_tokens"] == 128000
        assert result["max_output_tokens"] == 16384

    def test_case_insensitive(self):
        result = _resolve_model_limits("GPT-4O")
        assert result["max_input_tokens"] == 128000

    def test_prefix_match(self):
        result = _resolve_model_limits("gpt-4o-2024-05-13")
        assert result["max_input_tokens"] == 128000

    def test_provider_prefix(self):
        result = _resolve_model_limits("openai/gpt-4o")
        assert result["max_input_tokens"] == 128000

    def test_unknown_model(self):
        result = _resolve_model_limits("unknown-model-xyz")
        assert result == DEFAULT_TOKEN_LIMITS

    def test_default_model(self):
        result = _resolve_model_limits(DEFAULT_MODEL_NAME)
        assert result["max_input_tokens"] == 131072


class TestResolveModelCapabilities:
    def test_gpt4o_has_vision(self):
        caps = _resolve_model_capabilities("gpt-4o")
        assert caps.supports_vision is True
        assert caps.supports_tools is True
        assert caps.supports_parallel_calls is True

    def test_deepseek_reasoner_no_tools(self):
        caps = _resolve_model_capabilities("deepseek-reasoner")
        assert caps.supports_tools is False

    def test_unknown_model_defaults(self):
        caps = _resolve_model_capabilities("nonexistent-model")
        assert isinstance(caps, ModelCapabilities)
        assert caps.supports_tools is True  # default
        assert caps.supports_vision is False

    def test_provider_prefix_resolution(self):
        caps = _resolve_model_capabilities("anthropic/claude-3.5-sonnet")
        assert caps.supports_vision is True


class TestModel:
    def test_default_model(self):
        m = Model()
        assert m.name == DEFAULT_MODEL_NAME

    def test_custom_model(self):
        m = Model("gpt-4o")
        assert m.name == "gpt-4o"

    def test_max_input_tokens_has_safety_margin(self):
        m = Model("gpt-4o")
        raw = m.info["max_input_tokens"]
        assert m.max_input_tokens == raw - CONTEXT_SAFETY_MARGIN

    def test_max_output_tokens(self):
        m = Model("gpt-4o")
        assert m.max_output_tokens == 16384

    def test_backend_model_mapping(self):
        m = Model("machao-flash")
        assert m.backend_model == "deepseek/deepseek-chat"
        m2 = Model("machao-pro")
        assert m2.backend_model == "deepseek/deepseek-reasoner"

    def test_backend_model_passthrough(self):
        m = Model("gpt-4o")
        assert m.backend_model == "gpt-4o"

    def test_capabilities_populated(self):
        m = Model("gpt-4o")
        assert isinstance(m.capabilities, ModelCapabilities)

    def test_repr(self):
        m = Model("gpt-4o")
        assert repr(m) == "Model(gpt-4o)"

    def test_weak_model_is_self(self):
        m = Model("gpt-4o")
        assert m.weak_model is m


class TestModelTokenLimitsDict:
    def test_contains(self):
        assert "gpt-4o" in MODEL_TOKEN_LIMITS

    def test_getitem(self):
        limits = MODEL_TOKEN_LIMITS["gpt-4o"]
        assert "max_input_tokens" in limits
        assert "max_output_tokens" in limits

    def test_iter(self):
        names = list(MODEL_TOKEN_LIMITS)
        assert "gpt-4o" in names

    def test_keys_values_items(self):
        assert len(MODEL_TOKEN_LIMITS.keys()) > 0
        assert len(MODEL_TOKEN_LIMITS.values()) > 0
        for name, limits in MODEL_TOKEN_LIMITS.items():
            assert "max_input_tokens" in limits


class TestLoadModels:
    def test_builtin_models_loaded(self):
        models = _load_models()
        assert "gpt-4o" in models
        assert "claude-3.5-sonnet" in models
        assert "deepseek-chat" in models

    def test_reload_clears_cache(self):
        _load_models()
        reload_models()
        from aicoder import models as m
        assert m._merged_models is None
