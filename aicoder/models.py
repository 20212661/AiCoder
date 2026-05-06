"""模型配置与 API 调用模块

特性：
- 内置模型列表 + 外部 JSON 扩展（~/.aicoder/models.json）
- 模型能力元数据（vision, tools, streaming）
- 连通性测试
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .llm import litellm

DEFAULT_MODEL_NAME = "machao-flash"

# ── 模型能力元数据 ──────────────────────────────────────────

@dataclass
class ModelCapabilities:
    """声明模型支持的能力，供工具系统和 UI 查询"""
    supports_vision: bool = False
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_system_messages: bool = True
    supports_parallel_calls: bool = False


# ── 内置模型配置 ────────────────────────────────────────────

# 每个模型条目包含 token 限制和能力声明
_BUILTIN_MODELS: dict[str, dict[str, Any]] = {
    "gpt-4o": {"max_input_tokens": 128000, "max_output_tokens": 16384,
               "capabilities": {"supports_vision": True, "supports_tools": True, "supports_parallel_calls": True}},
    "gpt-4o-mini": {"max_input_tokens": 128000, "max_output_tokens": 16384,
                     "capabilities": {"supports_vision": True, "supports_tools": True}},
    "gpt-4-turbo": {"max_input_tokens": 128000, "max_output_tokens": 4096,
                     "capabilities": {"supports_vision": True, "supports_tools": True}},
    "gpt-4": {"max_input_tokens": 8192, "max_output_tokens": 4096,
              "capabilities": {"supports_tools": True}},
    "gpt-4-32k": {"max_input_tokens": 32768, "max_output_tokens": 4096,
                   "capabilities": {"supports_tools": True}},
    "gpt-3.5-turbo": {"max_input_tokens": 16385, "max_output_tokens": 4096,
                       "capabilities": {"supports_tools": True}},
    "gpt-3.5-turbo-16k": {"max_input_tokens": 16385, "max_output_tokens": 4096,
                           "capabilities": {"supports_tools": True}},
    "o1": {"max_input_tokens": 200000, "max_output_tokens": 100000,
            "capabilities": {"supports_vision": True, "supports_tools": True}},
    "o1-mini": {"max_input_tokens": 128000, "max_output_tokens": 65536,
                 "capabilities": {"supports_tools": True}},
    "o3-mini": {"max_input_tokens": 200000, "max_output_tokens": 100000,
                 "capabilities": {"supports_vision": True, "supports_tools": True}},
    "claude-3.5-sonnet": {"max_input_tokens": 200000, "max_output_tokens": 8192,
                           "capabilities": {"supports_vision": True, "supports_tools": True, "supports_parallel_calls": True}},
    "claude-3-opus": {"max_input_tokens": 200000, "max_output_tokens": 4096,
                       "capabilities": {"supports_vision": True, "supports_tools": True}},
    "claude-3-haiku": {"max_input_tokens": 200000, "max_output_tokens": 4096,
                        "capabilities": {"supports_vision": True, "supports_tools": True}},
    "claude-3-sonnet": {"max_input_tokens": 200000, "max_output_tokens": 4096,
                         "capabilities": {"supports_vision": True, "supports_tools": True}},
    "deepseek-chat": {"max_input_tokens": 131072, "max_output_tokens": 8192,
                       "capabilities": {"supports_tools": True}},
    "deepseek-coder": {"max_input_tokens": 131072, "max_output_tokens": 8192,
                         "capabilities": {"supports_tools": True}},
    "deepseek-reasoner": {"max_input_tokens": 131072, "max_output_tokens": 8192,
                            "capabilities": {"supports_tools": False}},
    "machao-flash": {"max_input_tokens": 131072, "max_output_tokens": 8192,
                      "capabilities": {"supports_tools": True}},
    "machao-pro": {"max_input_tokens": 131072, "max_output_tokens": 8192,
                    "capabilities": {"supports_tools": False}},
    "gemini-2.0-flash": {"max_input_tokens": 1048576, "max_output_tokens": 8192,
                          "capabilities": {"supports_vision": True, "supports_tools": True}},
    "gemini-1.5-pro": {"max_input_tokens": 2097152, "max_output_tokens": 8192,
                        "capabilities": {"supports_vision": True, "supports_tools": True}},
    "gemini-1.5-flash": {"max_input_tokens": 1048576, "max_output_tokens": 8192,
                          "capabilities": {"supports_vision": True, "supports_tools": True}},
    "llama-3.3-70b": {"max_input_tokens": 128000, "max_output_tokens": 4096,
                       "capabilities": {"supports_tools": True}},
    "llama-3.1-405b": {"max_input_tokens": 128000, "max_output_tokens": 4096,
                        "capabilities": {"supports_tools": True}},
}

MACHO_BACKEND_MAP = {"machao-flash": "deepseek/deepseek-chat", "machao-pro": "deepseek/deepseek-reasoner"}
DEFAULT_TOKEN_LIMITS = {"max_input_tokens": 131072, "max_output_tokens": 8192}
CONTEXT_SAFETY_MARGIN = 4096

# ── 外部 JSON 模型扩展 ──────────────────────────────────────

_MODELS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".aicoder", "models.json")
_merged_models: dict[str, dict[str, Any]] | None = None


def _load_models() -> dict[str, dict[str, Any]]:
    """加载模型配置（内置 + 用户扩展）

    用户扩展文件格式 ~/.aicoder/models.json：
    {
        "my-custom-model": {
            "max_input_tokens": 32768,
            "max_output_tokens": 4096,
            "capabilities": {"supports_vision": false, "supports_tools": true}
        }
    }
    """
    global _merged_models
    if _merged_models is not None:
        return _merged_models

    _merged_models = dict(_BUILTIN_MODELS)

    if os.path.isfile(_MODELS_JSON_PATH):
        try:
            with open(_MODELS_JSON_PATH, "r", encoding="utf-8") as f:
                user_models = json.load(f)
            if isinstance(user_models, dict):
                for name, config in user_models.items():
                    if isinstance(config, dict):
                        # 补全默认值
                        config.setdefault("max_input_tokens", DEFAULT_TOKEN_LIMITS["max_input_tokens"])
                        config.setdefault("max_output_tokens", DEFAULT_TOKEN_LIMITS["max_output_tokens"])
                        config.setdefault("capabilities", {})
                        _merged_models[name] = config
        except (json.JSONDecodeError, OSError) as err:
            logging.warning("Failed to load %s: %s", _MODELS_JSON_PATH, err)

    return _merged_models


def reload_models():
    """强制重新加载模型配置（用于测试或用户修改 models.json 后）"""
    global _merged_models
    _merged_models = None


# ── 兼容旧代码的 MODEL_TOKEN_LIMITS ───────────────────────

def _model_token_limits():
    """向后兼容：返回 {name: {max_input_tokens, max_output_tokens}}"""
    models = _load_models()
    return {name: {k: v for k, v in cfg.items() if k in ("max_input_tokens", "max_output_tokens")}
            for name, cfg in models.items()}


class _ModelTokenLimitsDict(dict):
    """惰性字典 — 首次访问时加载，兼容旧代码 MODEL_TOKEN_LIMITS[name]"""
    def __init__(self):
        super().__init__()
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.update(_model_token_limits())
            self._loaded = True

    def __contains__(self, key):
        self._ensure_loaded()
        return super().__contains__(key)

    def __getitem__(self, key):
        self._ensure_loaded()
        return super().__getitem__(key)

    def __iter__(self):
        self._ensure_loaded()
        return super().__iter__()

    def keys(self):
        self._ensure_loaded()
        return super().keys()

    def values(self):
        self._ensure_loaded()
        return super().values()

    def items(self):
        self._ensure_loaded()
        return super().items()


MODEL_TOKEN_LIMITS = _ModelTokenLimitsDict()


# ── 模型解析 ────────────────────────────────────────────────

def _get_sorted_keys():
    return sorted(_load_models().keys(), key=len, reverse=True)


def _resolve_model_limits(model_name: str) -> dict[str, int]:
    """解析模型的 token 限制"""
    models = _load_models()
    ml = model_name.lower()

    if ml in models:
        cfg = models[ml]
        return {"max_input_tokens": cfg["max_input_tokens"], "max_output_tokens": cfg["max_output_tokens"]}

    sorted_keys = _get_sorted_keys()
    for k in sorted_keys:
        if ml.startswith(k):
            cfg = models[k]
            return {"max_input_tokens": cfg["max_input_tokens"], "max_output_tokens": cfg["max_output_tokens"]}

    if "/" in ml:
        bn = ml.split("/", 1)[1]
        if bn in models:
            cfg = models[bn]
            return {"max_input_tokens": cfg["max_input_tokens"], "max_output_tokens": cfg["max_output_tokens"]}
        for k in sorted_keys:
            if bn.startswith(k):
                cfg = models[k]
                return {"max_input_tokens": cfg["max_input_tokens"], "max_output_tokens": cfg["max_output_tokens"]}

    return dict(DEFAULT_TOKEN_LIMITS)


def _resolve_model_capabilities(model_name: str) -> ModelCapabilities:
    """解析模型的能力元数据"""
    models = _load_models()
    ml = model_name.lower()

    # 查找匹配的模型配置
    cfg = None
    if ml in models:
        cfg = models[ml]
    else:
        sorted_keys = _get_sorted_keys()
        for k in sorted_keys:
            if ml.startswith(k):
                cfg = models[k]
                break
        if cfg is None and "/" in ml:
            bn = ml.split("/", 1)[1]
            if bn in models:
                cfg = models[bn]
            else:
                for k in sorted_keys:
                    if bn.startswith(k):
                        cfg = models[k]
                        break

    if cfg and "capabilities" in cfg:
        caps = cfg["capabilities"]
        return ModelCapabilities(
            supports_vision=caps.get("supports_vision", False),
            supports_tools=caps.get("supports_tools", True),
            supports_streaming=caps.get("supports_streaming", True),
            supports_system_messages=caps.get("supports_system_messages", True),
            supports_parallel_calls=caps.get("supports_parallel_calls", False),
        )
    return ModelCapabilities()


# ── Model 类 ────────────────────────────────────────────────

class Model:
    def __init__(self, model_name=None):
        self.name = model_name or DEFAULT_MODEL_NAME
        self.edit_format = "whole"
        limits = _resolve_model_limits(self.name)
        self.info = {"max_input_tokens": limits["max_input_tokens"], "max_output_tokens": limits["max_output_tokens"]}
        self.capabilities = _resolve_model_capabilities(self.name)
        self.streaming = self.capabilities.supports_streaming
        self.weak_model = self

    @property
    def backend_model(self):
        return MACHO_BACKEND_MAP.get(self.name, self.name)

    @property
    def max_input_tokens(self):
        raw = self.info.get("max_input_tokens", DEFAULT_TOKEN_LIMITS["max_input_tokens"])
        return max(0, raw - CONTEXT_SAFETY_MARGIN)

    @property
    def max_output_tokens(self):
        return self.info.get("max_output_tokens", DEFAULT_TOKEN_LIMITS["max_output_tokens"])

    def send_completion(self, messages, functions=None, stream=False, temperature=None):
        kwargs = dict(model=self.backend_model, messages=messages, stream=stream)
        kwargs["max_tokens"] = self.max_output_tokens
        kwargs["timeout"] = 60  # 60秒超时，防止无限挂起
        if temperature is not None:
            kwargs["temperature"] = temperature
        if functions:
            kwargs["functions"] = functions
        return litellm.completion(**kwargs)

    def simple_send(self, messages):
        try:
            r = self.send_completion(messages, stream=False)
            return r.choices[0].message.content
        except Exception as err:
            logging.error("API call failed for model %s: %s", self.name, err)
            return None

    def test_connection(self, timeout: float = 10.0) -> tuple[bool, str]:
        """测试模型 API 连通性

        Returns:
            (success, message) 元组
        """
        try:
            start = time.time()
            response = litellm.completion(
                model=self.backend_model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
                stream=False,
                timeout=timeout,
            )
            latency = time.time() - start
            content = response.choices[0].message.content if response.choices else ""
            return True, f"OK ({latency:.1f}s) — {content[:50]}"
        except Exception as err:
            return False, str(err)[:200]

    def __repr__(self):
        return f"Model({self.name})"

    def token_count(self, messages):
        try:
            if isinstance(messages, str):
                return litellm.token_counter(model=self.backend_model, text=messages)
            elif isinstance(messages, list):
                return litellm.token_counter(model=self.backend_model, messages=messages)
        except Exception:
            logging.debug("token_count: litellm fallback — token counting unavailable for %s", self.backend_model)
        if isinstance(messages, str):
            return len(messages) // 4
        if isinstance(messages, dict):
            return len(messages.get("content", "")) // 4
        if isinstance(messages, list):
            t = 0
            for m in messages:
                if isinstance(m, dict):
                    t += len(m.get("content", ""))
                elif isinstance(m, str):
                    t += len(m)
            return t // 4
        return 0