"""
Voice synthesis service.

Supports multiple TTS providers:
- browser: Default browser SpeechSynthesis (fallback)
- http: External TTS API endpoint
- edge-tts: Microsoft Edge TTS via edge-tts library (no GPU, high quality Japanese voice)
"""
from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .settings import settings

# fmt: off
_XML_ESC = str.maketrans({
    "&": "&" + "amp;",
    "<": "&" + "lt;",
    ">": "&" + "gt;",
    '"': "&" + "quot;",
    "'": "&" + "apos;",
})
# fmt: on


def _escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return text.translate(_XML_ESC)


# Voice style -> SSML prosody adjustments for cool/assertive researcher personality
# Default: rate=-10% (slower), pitch=-3Hz (deeper) = calm, controlled, intelligent
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
        return {
            "provider": provider,
            "configured": provider in ("http", "edge-tts"),
            "voice": os.environ.get("ASSISTANT_TTS_VOICE", "ja-JP-NanamiNeural"),
            "fallback": "browser_speech_synthesis",
        }

    async def synthesize(self, text: str, voice_style: str) -> VoiceResult:
        provider = os.environ.get("ASSISTANT_TTS_PROVIDER", "browser").strip().lower() or "browser"

        if provider == "edge-tts":
            return await self._synthesize_edge(text, voice_style)

        endpoint = os.environ.get("ASSISTANT_TTS_ENDPOINT", "").strip()
        if provider == "http" and endpoint:
            return await self._synthesize_http(text, voice_style, endpoint)

        return VoiceResult(
            audio_url=None, engine="browser", reason="No backend TTS endpoint configured."
        )

    async def _synthesize_edge(self, text: str, voice_style: str) -> VoiceResult:
        """Use Microsoft Edge TTS (edge-tts library) for natural Japanese speech.

        IMPORTANT: Only the pure `text` (ja_text) is sent to the TTS engine.
        NO SSML/XML wrapping is done here - the edge-tts library handles internal
        SSML wrapping automatically. Passing SSML as the text would cause the
        engine to read out XML tags as speech.

        Voice: ja-JP-NanamiNeural - mature, calm female Japanese voice.
        Pitch/rate: slightly slower rate + lower pitch = cool/calm/assertive style.
        """
        try:
            import edge_tts
        except ImportError:
            return VoiceResult(
                audio_url=None, engine="edge-tts", reason="edge-tts library not installed."
            )

        style_cfg = VOICE_STYLE_MAP.get(voice_style, VOICE_STYLE_MAP["normal"])
        style_pitch = style_cfg["pitch"]
        style_rate = style_cfg["rate"]

        voice = os.environ.get("ASSISTANT_TTS_VOICE", "ja-JP-NanamiNeural")

        communicate = edge_tts.Communicate(
            text,
            voice,
            rate=style_rate,
            pitch=style_pitch,
        )
        audio_bytes = b""
        try:
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    audio_bytes += chunk["data"]
        except Exception as exc:
            return VoiceResult(
                audio_url=None, engine="edge-tts", reason=f"Edge TTS stream failed: {exc}"
            )

        if not audio_bytes:
            return VoiceResult(audio_url=None, engine="edge-tts", reason="Edge TTS returned empty audio.")

        return self._write_audio(audio_bytes, ".mp3", "edge-tts")

    async def _synthesize_http(self, text: str, voice_style: str, endpoint: str) -> VoiceResult:
        payload = {
            "text": text,
            "language": "ja-JP",
            "voice": os.environ.get("ASSISTANT_TTS_VOICE", "cold_researcher_ja"),
            "style": voice_style,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
        except Exception as exc:
            return VoiceResult(audio_url=None, engine="http", reason=str(exc))

        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type.startswith("audio/"):
            suffix = self._suffix_for_content_type(content_type)
            return self._write_audio(response.content, suffix, "http")

        try:
            data = response.json()
        except ValueError:
            return VoiceResult(
                audio_url=None, engine="http", reason="TTS endpoint returned non-audio, non-JSON data."
            )

        if isinstance(data, dict) and isinstance(data.get("audio_url"), str):
            return VoiceResult(audio_url=data["audio_url"], engine="http")

        if isinstance(data, dict) and isinstance(data.get("audio_base64"), str):
            fmt = str(data.get("format") or "wav").strip(".").lower()
            try:
                audio_bytes = base64.b64decode(data["audio_base64"])
            except Exception as exc:
                return VoiceResult(audio_url=None, engine="http", reason=f"Invalid audio_base64: {exc}")
            return self._write_audio(audio_bytes, f".{fmt}", "http")

        return VoiceResult(
            audio_url=None, engine="http", reason="TTS JSON did not include audio_url or audio_base64."
        )

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