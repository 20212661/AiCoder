"""模型配置与 API 调用模块"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any, Optional
from .llm import litellm

DEFAULT_MODEL_NAME = "machao-flash"

MODEL_TOKEN_LIMITS = {
    "gpt-4o": {"max_input_tokens": 128000, "max_output_tokens": 16384},
    "gpt-4o-mini": {"max_input_tokens": 128000, "max_output_tokens": 16384},
    "gpt-4-turbo": {"max_input_tokens": 128000, "max_output_tokens": 4096},
    "gpt-4": {"max_input_tokens": 8192, "max_output_tokens": 4096},
    "gpt-4-32k": {"max_input_tokens": 32768, "max_output_tokens": 4096},
    "gpt-3.5-turbo": {"max_input_tokens": 16385, "max_output_tokens": 4096},
    "gpt-3.5-turbo-16k": {"max_input_tokens": 16385, "max_output_tokens": 4096},
    "o1": {"max_input_tokens": 200000, "max_output_tokens": 100000},
    "o1-mini": {"max_input_tokens": 128000, "max_output_tokens": 65536},
    "o3-mini": {"max_input_tokens": 200000, "max_output_tokens": 100000},
    "claude-3.5-sonnet": {"max_input_tokens": 200000, "max_output_tokens": 8192},
    "claude-3-opus": {"max_input_tokens": 200000, "max_output_tokens": 4096},
    "claude-3-haiku": {"max_input_tokens": 200000, "max_output_tokens": 4096},
    "claude-3-sonnet": {"max_input_tokens": 200000, "max_output_tokens": 4096},
    "deepseek-chat": {"max_input_tokens": 131072, "max_output_tokens": 8192},
    "deepseek-coder": {"max_input_tokens": 131072, "max_output_tokens": 8192},
    "deepseek-reasoner": {"max_input_tokens": 131072, "max_output_tokens": 8192},
    "machao-flash": {"max_input_tokens": 131072, "max_output_tokens": 8192},
    "machao-pro": {"max_input_tokens": 131072, "max_output_tokens": 8192},
    "gemini-2.0-flash": {"max_input_tokens": 1048576, "max_output_tokens": 8192},
    "gemini-1.5-pro": {"max_input_tokens": 2097152, "max_output_tokens": 8192},
    "gemini-1.5-flash": {"max_input_tokens": 1048576, "max_output_tokens": 8192},
    "llama-3.3-70b": {"max_input_tokens": 128000, "max_output_tokens": 4096},
    "llama-3.1-405b": {"max_input_tokens": 128000, "max_output_tokens": 4096},
}

MACHO_BACKEND_MAP = {"machao-flash": "deepseek/deepseek-chat", "machao-pro": "deepseek/deepseek-reasoner"}
DEFAULT_TOKEN_LIMITS = {"max_input_tokens": 131072, "max_output_tokens": 8192}
CONTEXT_SAFETY_MARGIN = 4096

def _resolve_model_limits(model_name):
    ml = model_name.lower()
    if ml in MODEL_TOKEN_LIMITS: return MODEL_TOKEN_LIMITS[ml]
    sk = sorted(MODEL_TOKEN_LIMITS.keys(), key=len, reverse=True)
    for k in sk:
        if ml.startswith(k): return MODEL_TOKEN_LIMITS[k]
    if "/" in ml:
        bn = ml.split("/", 1)[1]
        if bn in MODEL_TOKEN_LIMITS: return MODEL_TOKEN_LIMITS[bn]
        for k in sk:
            if bn.startswith(k): return MODEL_TOKEN_LIMITS[k]
    return dict(DEFAULT_TOKEN_LIMITS)

class Model:
    def __init__(self, model_name=None):
        self.name = model_name or DEFAULT_MODEL_NAME
        self.edit_format = "whole"
        limits = _resolve_model_limits(self.name)
        self.info = {"max_input_tokens": limits["max_input_tokens"], "max_output_tokens": limits["max_output_tokens"]}
        self.streaming = True
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
        if temperature is not None: kwargs["temperature"] = temperature
        if functions: kwargs["functions"] = functions
        return litellm.completion(**kwargs)

    def simple_send(self, messages):
        try:
            r = self.send_completion(messages, stream=False)
            return r.choices[0].message.content
        except Exception as err:
            print("API fail: " + str(err))
            return None

    def __repr__(self): return "Model(" + self.name + ")"

    def token_count(self, messages):
        try:
            if isinstance(messages, str): return litellm.token_counter(model=self.backend_model, text=messages)
            elif isinstance(messages, list): return litellm.token_counter(model=self.backend_model, messages=messages)
        except Exception: pass
        if isinstance(messages, str): return len(messages) // 4
        if isinstance(messages, dict): return len(messages.get("content", "")) // 4
        if isinstance(messages, list):
            t = 0
            for m in messages:
                if isinstance(m, dict): t += len(m.get("content", ""))
                elif isinstance(m, str): t += len(m)
            return t // 4
        return 0
