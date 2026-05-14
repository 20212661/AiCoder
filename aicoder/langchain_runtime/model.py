from __future__ import annotations

from langchain_litellm import ChatLiteLLM


def build_chat_model(model_name: str) -> ChatLiteLLM:
    return ChatLiteLLM(
        model=model_name,
        temperature=0,
    )
