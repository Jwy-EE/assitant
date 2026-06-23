from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AsrResult:
    ok: bool
    text: str
    engine: str
    confidence: float = 0.0
    duration_ms: float = 0.0
    reason: str | None = None


class AsrService:
    def __init__(self) -> None:
        self._whisper_model = None

    def status(self) -> dict[str, Any]:
        provider = os.environ.get("ASSISTANT_ASR_PROVIDER", "google").strip().lower() or "google"
        return {
            "provider": provider,
            "language": "zh-CN",
            "input_format": "audio/wav",
        }

    def _get_provider(self) -> str:
        return os.environ.get("ASSISTANT_ASR_PROVIDER", "google").strip().lower() or "google"

    def transcribe_wav(self, audio_bytes: bytes, language: str = "zh-CN") -> AsrResult:
        provider = self._get_provider()
        t0 = time.perf_counter()

        if provider == "faster_whisper":
            return self._transcribe_faster_whisper(audio_bytes, language, t0)

        # fallback: google speech recognition
        return self._transcribe_google(audio_bytes, language, t0)

    def _transcribe_google(self, audio_bytes: bytes, language: str, t0: float) -> AsrResult:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
                audio = recognizer.record(source)
            text = recognizer.recognize_google(audio, language=language)
        except sr.UnknownValueError:
            elapsed = (time.perf_counter() - t0) * 1000
            return AsrResult(ok=False, text="", engine="google", confidence=0.0, duration_ms=elapsed, reason="Could not recognize speech.")
        except sr.RequestError as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            return AsrResult(ok=False, text="", engine="google", confidence=0.0, duration_ms=elapsed, reason=f"ASR request failed: {exc}")
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            return AsrResult(ok=False, text="", engine="google", confidence=0.0, duration_ms=elapsed, reason=str(exc))

        elapsed = (time.perf_counter() - t0) * 1000
        # Google doesn't expose confidence, use a reasonable default
        return AsrResult(ok=True, text=text.strip(), engine="google", confidence=0.8, duration_ms=round(elapsed, 1))

    def _transcribe_faster_whisper(self, audio_bytes: bytes, language: str, t0: float) -> AsrResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            elapsed = (time.perf_counter() - t0) * 1000
            return AsrResult(ok=False, text="", engine="faster_whisper", confidence=0.0, duration_ms=elapsed, reason="faster-whisper not installed. Run: pip install faster-whisper")

        model_name = os.environ.get("ASSISTANT_ASR_MODEL", "base").strip() or "base"
        device = os.environ.get("ASSISTANT_ASR_DEVICE", "auto").strip() or "auto"
        compute = os.environ.get("ASSISTANT_ASR_COMPUTE", "float16").strip() or "float16"

        if device == "auto":
            device = "cuda" if self._has_cuda() else "cpu"

        try:
            if self._whisper_model is None:
                self._whisper_model = WhisperModel(
                    model_name,
                    device=device,
                    compute_type=compute if device == "cuda" else "default",
                )

            # Write audio bytes to a temporary file for faster-whisper
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            try:
                segments, info = self._whisper_model.transcribe(
                    tmp_path,
                    language=language.split("-")[0],
                    beam_size=5,
                    vad_filter=True,
                )
                text = " ".join(seg.text for seg in segments).strip()
                confidence = info.average_log_prob if info is not None else 0.0
                # Normalize confidence to 0-1 range (whisper avg_log_prob is typically -1 to 0)
                confidence = max(0.0, min(1.0, (confidence + 1.0) / 2.0))
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            elapsed = (time.perf_counter() - t0) * 1000
            return AsrResult(
                ok=bool(text),
                text=text or "",
                engine="faster_whisper",
                confidence=round(confidence, 4),
                duration_ms=round(elapsed, 1),
                reason=None if text else "No speech detected.",
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            return AsrResult(ok=False, text="", engine="faster_whisper", confidence=0.0, duration_ms=elapsed, reason=str(exc))

    @staticmethod
    def _has_cuda() -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False