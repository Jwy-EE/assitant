from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


DIVERGENCE_API_BASE = "https://divergence.nyarchlinux.moe/api"


@dataclass(frozen=True)
class DivergenceReading:
    divergence: str
    source: str = DIVERGENCE_API_BASE


class DivergenceMeter:
    def __init__(self, base_url: str = DIVERGENCE_API_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    async def current(self) -> DivergenceReading:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(f"{self.base_url}/divergence")
            response.raise_for_status()
        data = response.json()
        return DivergenceReading(divergence=str(data.get("divergence", "")))

    async def news(
        self,
        page: int = 1,
        per_page: int = 10,
        min_impact: float | None = None,
        max_impact: float | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "page": str(max(1, page)),
            "per_page": str(max(1, min(per_page, 25))),
        }
        if min_impact is not None:
            params["min_impact"] = str(min_impact)
        if max_impact is not None:
            params["max_impact"] = str(max_impact)

        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(f"{self.base_url}/news", params=params)
            response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"items": data}
