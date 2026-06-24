from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_AUDIO = REPO_ROOT / "Amadeus-main" / "Voices" / "OneShot" / "CRS_JP.wav"
DEFAULT_REFERENCE_TEXT = DEFAULT_REFERENCE_AUDIO.with_suffix(DEFAULT_REFERENCE_AUDIO.suffix + ".txt")
DEFAULT_WARMUP_TEXT = "愛してる。"


def _read_reference_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _normalize_audio_path(path: Path) -> str:
    return path.resolve().as_posix()


@dataclass(frozen=True)
class GPTSoVITSConfig:
    api_base: str
    tts_path: str
    prompt_lang: str
    text_lang: str
    ref_audio_path: Path
    ref_text_path: Path
    text_split_method: str
    batch_size: int
    speed_factor: float
    top_k: int
    top_p: float
    temperature: float
    repetition_penalty: float
    media_type: str
    streaming_mode: bool
    timeout_seconds: float

    @property
    def tts_url(self) -> str:
        return f"{self.api_base.rstrip('/')}/{self.tts_path.lstrip('/')}"

    @classmethod
    def from_env(cls) -> "GPTSoVITSConfig":
        return cls(
            api_base=os.environ.get("GPT_SOVITS_API_BASE", "http://127.0.0.1:9880").strip(),
            tts_path=os.environ.get("GPT_SOVITS_TTS_PATH", "/tts").strip(),
            prompt_lang=os.environ.get("GPT_SOVITS_PROMPT_LANG", "ja").strip(),
            text_lang=os.environ.get("GPT_SOVITS_TEXT_LANG", "ja").strip(),
            ref_audio_path=Path(
                os.environ.get("GPT_SOVITS_REF_AUDIO", str(DEFAULT_REFERENCE_AUDIO))
            ).expanduser(),
            ref_text_path=Path(
                os.environ.get("GPT_SOVITS_REF_TEXT", str(DEFAULT_REFERENCE_TEXT))
            ).expanduser(),
            text_split_method=os.environ.get("GPT_SOVITS_SPLIT_METHOD", "cut5").strip(),
            batch_size=int(os.environ.get("GPT_SOVITS_BATCH_SIZE", "1")),
            speed_factor=float(os.environ.get("GPT_SOVITS_SPEED", "1.0")),
            top_k=int(os.environ.get("GPT_SOVITS_TOP_K", "15")),
            top_p=float(os.environ.get("GPT_SOVITS_TOP_P", "1.0")),
            temperature=float(os.environ.get("GPT_SOVITS_TEMPERATURE", "1.0")),
            repetition_penalty=float(os.environ.get("GPT_SOVITS_REPETITION_PENALTY", "1.35")),
            media_type=os.environ.get("GPT_SOVITS_MEDIA_TYPE", "wav").strip(),
            streaming_mode=os.environ.get("GPT_SOVITS_STREAMING", "").strip().lower() in {"1", "true", "yes"},
            timeout_seconds=float(os.environ.get("GPT_SOVITS_TIMEOUT", "120")),
        )


class GPTSoVITSClient:
    def __init__(self, config: GPTSoVITSConfig | None = None) -> None:
        self.config = config or GPTSoVITSConfig.from_env()

    def validate(self) -> list[str]:
        issues: list[str] = []
        if not self.config.ref_audio_path.exists():
            issues.append(f"reference audio not found: {self.config.ref_audio_path}")
        if not self.config.ref_text_path.exists():
            issues.append(f"reference text not found: {self.config.ref_text_path}")
        return issues

    def status(self) -> dict[str, Any]:
        issues = self.validate()
        return {
            "mode": "gpt-sovits",
            "api_base": self.config.api_base,
            "tts_url": self.config.tts_url,
            "reference_audio": str(self.config.ref_audio_path),
            "reference_text": str(self.config.ref_text_path),
            "ready": not issues,
            "issues": issues,
        }

    def healthcheck(self) -> dict[str, Any]:
        state = self.status()
        if state["issues"]:
            return state

        try:
            with httpx.Client(timeout=min(self.config.timeout_seconds, 8.0)) as client:
                response = client.post(self.config.tts_url, json={})
        except Exception as exc:
            state["ready"] = False
            state["issues"] = [*state["issues"], f"probe failed: {exc}"]
            return state

        if response.status_code in {200, 400, 422}:
            state["ready"] = True
            state["probe_status"] = response.status_code
            return state

        state["ready"] = False
        state["issues"] = [*state["issues"], f"unexpected probe status: {response.status_code}"]
        return state

    def synthesize(self, text: str) -> bytes:
        issues = self.validate()
        if issues:
            raise RuntimeError("; ".join(issues))

        payload = {
            "text": text,
            "text_lang": self.config.text_lang,
            "ref_audio_path": _normalize_audio_path(self.config.ref_audio_path),
            "prompt_text": _read_reference_text(self.config.ref_text_path),
            "prompt_lang": self.config.prompt_lang,
            "text_split_method": self.config.text_split_method,
            "batch_size": self.config.batch_size,
            "speed_factor": self.config.speed_factor,
            "top_k": self.config.top_k,
            "top_p": self.config.top_p,
            "temperature": self.config.temperature,
            "repetition_penalty": self.config.repetition_penalty,
            "media_type": self.config.media_type,
            "streaming_mode": self.config.streaming_mode,
        }

        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(self.config.tts_url, json=payload)
            response.raise_for_status()
            return self._decode_audio_response(response)

    def warmup(self, text: str | None = None) -> bytes:
        warmup_text = (text or os.environ.get("GPT_SOVITS_WARMUP_TEXT") or DEFAULT_WARMUP_TEXT).strip()
        if not warmup_text:
            warmup_text = DEFAULT_WARMUP_TEXT
        return self.synthesize(warmup_text)

    def _decode_audio_response(self, response: httpx.Response) -> bytes:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type.startswith("audio/"):
            return response.content

        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("audio_base64"), str):
            return base64.b64decode(data["audio_base64"])
        if isinstance(data, dict) and isinstance(data.get("data"), str):
            return base64.b64decode(data["data"])
        if isinstance(data, dict) and isinstance(data.get("audio_url"), str):
            audio_response = httpx.get(data["audio_url"], timeout=self.config.timeout_seconds)
            audio_response.raise_for_status()
            return audio_response.content
        raise RuntimeError("GPT-SoVITS response did not contain audio bytes")