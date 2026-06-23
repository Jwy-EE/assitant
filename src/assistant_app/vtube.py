from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .settings import settings


@dataclass
class VTubeEvent:
    emotion: str
    gesture: str
    voice_style: str = "normal"


class VTubeStudioClient:
    def __init__(self, url: str = settings.vtube_url) -> None:
        self.url = url

    async def emit(self, event: VTubeEvent) -> dict[str, Any]:
        try:
            import websockets
        except ImportError:
            return {"connected": False, "reason": "websockets package is not installed"}

        # This is intentionally conservative: it verifies that VTube Studio is
        # reachable. Real hotkey names are user-configured and should be mapped
        # in data/app_config.json before sending production hotkey requests.
        try:
            async with websockets.connect(self.url, open_timeout=1.5) as ws:
                request = {
                    "apiName": "VTubeStudioPublicAPI",
                    "apiVersion": "1.0",
                    "requestID": "assistant-status",
                    "messageType": "APIStateRequest",
                    "data": {},
                }
                await ws.send(json.dumps(request))
                response = await ws.recv()
                return {
                    "connected": True,
                    "event": event.__dict__,
                    "api_state": json.loads(response),
                }
        except Exception as exc:  # pragma: no cover - depends on local app
            return {"connected": False, "reason": str(exc), "event": event.__dict__}

