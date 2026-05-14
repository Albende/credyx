"""LLM provider abstraction.

The only provider in MVP is `KieAIGeminiProvider`, which talks to kie.ai's
Gemini-compatible HTTP endpoint. The interface is kept narrow so we can later
swap in direct Google AI Studio, OpenRouter, or self-hosted models without
touching call sites.
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Run the model and return a parsed JSON dict."""


class KieAIGeminiProvider(LLMProvider):
    """Gemini family via kie.ai.

    kie.ai exposes Google Gemini models behind an OpenAI-compatible
    `/v1/chat/completions` interface. We use that here. JSON mode is requested
    via `response_format`; if the model still wraps output in code fences, the
    LLMService layer strips them.
    """

    name = "kie.ai/gemini"

    BASE_URL = "https://api.kie.ai/v1"
    DEFAULT_MODEL = "gemini-2.0-flash"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.getenv("KIE_AI_API_KEY")
        self.model = model or os.getenv("KIE_AI_MODEL") or self.DEFAULT_MODEL
        self.base_url = (base_url or os.getenv("KIE_AI_BASE_URL") or self.BASE_URL).rstrip("/")
        self.timeout = timeout

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "KIE_AI_API_KEY is not set. Set it in your environment to use the LLM service."
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if schema_hint:
            payload["messages"][0]["content"] += (
                "\n\nReturn JSON matching exactly this schema:\n"
                + json.dumps(schema_hint, indent=2)
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"kie.ai returned {resp.status_code}: {resp.text[:500]}"
                )
            data = resp.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected kie.ai response shape: {data}") from exc

        return _parse_json_loose(content)


def _parse_json_loose(content: str) -> dict[str, Any]:
    """Parse JSON that may be wrapped in code fences or have leading prose."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    # Find the first { ... } block.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output: {content[:300]!r}")
    return json.loads(stripped[start : end + 1])
