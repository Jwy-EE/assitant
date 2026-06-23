from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from ..settings import settings


@dataclass
class DeepSeekResponse:
    raw_text: str
    parsed: dict[str, Any]


class DeepSeekClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = settings.deepseek_base_url,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat_json(
        self,
        system_prompt: str,
        user_text: str,
        model: str = settings.default_model,
    ) -> DeepSeekResponse:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        raw_text = data["choices"][0]["message"]["content"]
        return DeepSeekResponse(raw_text=raw_text, parsed=_parse_json(raw_text))


def _parse_json(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw_text[start : end + 1])
        raise

