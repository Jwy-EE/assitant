from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Any

import speech_recognition as sr


@dataclass(frozen=True)
class AsrResult:
    ok: bool
    text: str
    engine: str
    reason: str | None = None


class AsrService:
    def status(self) -> dict[str, Any]:
        provider = os.environ.get("ASSISTANT_ASR_PROVIDER", "google").strip().lower() or "google"
        return {
            "provider": provider,
            "language": "zh-CN",
            "input_format": "audio/wav",
        }

    def transcribe_wav(self, audio_bytes: bytes, language: str = "zh-CN") -> AsrResult:
        provider = os.environ.get("ASSISTANT_ASR_PROVIDER", "google").strip().lower() or "google"
        if provider != "google":
            return AsrResult(ok=False, text="", engine=provider, reason="Unsupported ASR provider.")

        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
                audio = recognizer.record(source)
            text = recognizer.recognize_google(audio, language=language)
        except sr.UnknownValueError:
            return AsrResult(ok=False, text="", engine="google", reason="Could not recognize speech.")
        except sr.RequestError as exc:
            return AsrResult(ok=False, text="", engine="google", reason=f"ASR request failed: {exc}")
        except Exception as exc:
            return AsrResult(ok=False, text="", engine="google", reason=str(exc))
        return AsrResult(ok=True, text=text.strip(), engine="google")
