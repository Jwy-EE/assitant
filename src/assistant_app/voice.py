from __future__ import annotations

import asyncio
import base64
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .settings import settings


VOICE_STYLE_MAP: dict[str, dict[str, str]] = {
    "normal": {"pitch": "-3Hz", "rate": "-10%", "volume": "+0%"},
    "soft": {"pitch": "-2Hz", "rate": "-5%", "volume": "-10%"},
    "serious": {"pitch": "-5Hz", "rate": "-15%", "volume": "+5%"},
    "teasing": {"pitch": "-1Hz", "rate": "-5%", "volume": "+0%"},
}


@dataclass(frozen=True)
class VoiceResult:
    audio_url: str | None
    engine: str
    reason: str | None = None


class VoiceService:
    def __init__(self, audio_dir: Path = settings.audio_dir) -> None:
        self.audio_dir = audio_dir
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        provider = os.environ.get("ASSISTANT_TTS_PROVIDER", "browser").strip().lower() or "browser"
        endpoint = os.environ.get("ASSISTANT_TTS_ENDPOINT", "").strip()
        status = {
            "provider": provider,
            "configured": provider in ("http", "edge-tts"),
            "voice": os.environ.get("ASSISTANT_TTS_VOICE", "ja-JP-NanamiNeural"),
            "endpoint": endpoint,
            "fallback": "browser_speech_synthesis",
        }
        if provider == "http" and endpoint:
            bridge_url = endpoint.rsplit("/tts", 1)[0] + "/api/health"
            try:
                response = httpx.get(bridge_url, timeout=1.5)
                response.raise_for_status()
                status["backend"] = response.json()
            except Exception as exc:
                status["backend"] = {"status": "error", "reason": str(exc)}
        return status

    async def synthesize(self, text: str, voice_style: str) -> VoiceResult:
        provider = os.environ.get("ASSISTANT_TTS_PROVIDER", "browser").strip().lower() or "browser"
        if provider == "edge-tts":
            return await self._synthesize_edge(text, voice_style)

        endpoint = os.environ.get("ASSISTANT_TTS_ENDPOINT", "").strip()
        if provider == "http" and endpoint:
            return await self._synthesize_http(text, voice_style, endpoint)

        return VoiceResult(audio_url=None, engine="browser", reason="No backend TTS endpoint configured.")

    async def _synthesize_edge(self, text: str, voice_style: str) -> VoiceResult:
        try:
            import edge_tts
        except ImportError:
            return VoiceResult(audio_url=None, engine="edge-tts", reason="edge-tts library not installed.")

        style_cfg = VOICE_STYLE_MAP.get(voice_style, VOICE_STYLE_MAP["normal"])
        voice = os.environ.get("ASSISTANT_TTS_VOICE", "ja-JP-NanamiNeural")
        communicate = edge_tts.Communicate(text, voice, rate=style_cfg["rate"], pitch=style_cfg["pitch"])

        audio_bytes = b""
        try:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    audio_bytes += chunk["data"]
        except Exception as exc:
            return VoiceResult(audio_url=None, engine="edge-tts", reason=f"Edge TTS stream failed: {exc}")

        if not audio_bytes:
            return VoiceResult(audio_url=None, engine="edge-tts", reason="Edge TTS returned empty audio.")
        return self._write_audio(audio_bytes, ".mp3", "edge-tts")

    async def _synthesize_http(self, text: str, voice_style: str, endpoint: str) -> VoiceResult:
        payload = {
            "text": text,
            "language": "ja-JP",
            "voice": os.environ.get("ASSISTANT_TTS_VOICE", "kurisu_ja"),
            "style": voice_style,
        }
        last_error: str | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    response = await client.post(endpoint, json=payload)
                    response.raise_for_status()
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    await asyncio.sleep(0.8)
                    continue
                return VoiceResult(audio_url=None, engine="http", reason=last_error)

            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type.startswith("audio/"):
                return self._write_audio(response.content, self._suffix_for_content_type(content_type), "http")

            try:
                data = response.json()
            except ValueError:
                last_error = "TTS endpoint returned non-audio, non-JSON data."
                if attempt == 0:
                    await asyncio.sleep(0.8)
                    continue
                return VoiceResult(audio_url=None, engine="http", reason=last_error)

            if isinstance(data, dict) and isinstance(data.get("audio_url"), str):
                return VoiceResult(audio_url=data["audio_url"], engine="http")
            if isinstance(data, dict) and isinstance(data.get("audio_base64"), str):
                fmt = str(data.get("format") or "wav").strip(".").lower()
                try:
                    audio_bytes = base64.b64decode(data["audio_base64"])
                except Exception as exc:
                    last_error = f"Invalid audio_base64: {exc}"
                    if attempt == 0:
                        await asyncio.sleep(0.8)
                        continue
                    return VoiceResult(audio_url=None, engine="http", reason=last_error)
                return self._write_audio(audio_bytes, f".{fmt}", "http")

            last_error = "TTS JSON did not include audio_url or audio_base64."
            if attempt == 0:
                await asyncio.sleep(0.8)
                continue
            return VoiceResult(audio_url=None, engine="http", reason=last_error)

        return VoiceResult(audio_url=None, engine="http", reason=last_error or "Unknown HTTP TTS error.")

    def _write_audio(self, audio_bytes: bytes, suffix: str, engine: str) -> VoiceResult:
        filename = f"tts-{uuid.uuid4().hex}{suffix}"
        path = self.audio_dir / filename
        path.write_bytes(audio_bytes)
        return VoiceResult(audio_url=f"/audio/{filename}", engine=engine)

    def _suffix_for_content_type(self, content_type: str) -> str:
        return {
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/ogg": ".ogg",
            "audio/webm": ".webm",
        }.get(content_type, ".wav")
