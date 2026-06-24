from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent / "src"))

from assistant_app.gpt_sovits import GPTSoVITSClient

app = FastAPI(title="Kurisu Voice Clone API", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)
_engine: dict[str, Any] | None = None


def _fallback_engine() -> dict[str, Any]:
    from kurisu_voice_final import convert_wav_to_kurisu, text_to_kurisu

    def check_gpu() -> dict[str, Any]:
        return {"cuda_available": False, "device": "cpu", "model": "pyworld+stft-fallback"}

    return {
        "engine": "kurisu_final_fallback",
        "text_to_kurisu_voice": text_to_kurisu,
        "convert_wav_to_kurisu": convert_wav_to_kurisu,
        "check_gpu": check_gpu,
        "status": {"mode": "fallback", "ready": True, "fallback_used": True, "issues": []},
    }


def get_engine() -> dict[str, Any]:
    global _engine
    if _engine is not None:
        return _engine

    preferred_mode = (os.environ.get("KURISU_VOICE_MODE", "auto").strip().lower() or "auto")
    client = GPTSoVITSClient()
    client_status = client.healthcheck()
    gpt_ready = bool(client_status.get("ready"))

    if preferred_mode in {"gpt-sovits", "gpt_sovits", "auto"} and gpt_ready:
        _engine = {
            "engine": "gpt_sovits",
            "text_to_kurisu_voice": client.synthesize,
            "convert_wav_to_kurisu": None,
            "check_gpu": lambda: {"device": "remote", "model": "gpt-sovits-http"},
            "status": {**client_status, "fallback_used": False},
        }
    elif preferred_mode in {"gpt-sovits", "gpt_sovits"}:
        raise RuntimeError(f"GPT-SoVITS requested but not ready: {client_status.get('issues', [])}")
    else:
        _engine = _fallback_engine()
        _engine["status"] = {
            "mode": "fallback",
            "ready": True,
            "fallback_used": True,
            "issues": client_status.get("issues", []),
            "gpt_sovits": client_status,
        }

    logger.info("Voice engine initialized: %s", _engine["engine"])
    return _engine


class TTSRequest(BaseModel):
    text: str
    language: str = "ja-JP"
    voice: str = "kurisu_ja"
    style: str = "normal"


@app.get("/api/health")
async def health() -> dict[str, Any]:
    try:
        engine = get_engine()
    except Exception as exc:
        return {"status": "error", "engine": "unavailable", "reason": str(exc), "fallback_used": False}

    return {
        "status": "ok",
        "engine": engine["engine"],
        "gpu": engine["check_gpu"](),
        "fallback_used": bool(engine["status"].get("fallback_used")),
        "voice_backend": engine["status"],
    }


@app.post("/tts")
async def tts(request: TTSRequest) -> Response:
    try:
        engine = get_engine()
        logger.info(
            "TTS request engine=%s language=%s style=%s text=%r",
            engine["engine"],
            request.language,
            request.style,
            request.text[:80],
        )
        audio_bytes = engine["text_to_kurisu_voice"](request.text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice synthesis failed: {exc}") from exc

    if not audio_bytes:
        raise HTTPException(status_code=500, detail="Voice synthesis returned empty audio")

    return Response(content=audio_bytes, media_type="audio/wav", headers={"Content-Disposition": "inline; filename=kurisu_output.wav"})


@app.post("/convert")
async def convert_wav(file: bytes) -> Response:
    engine = get_engine()
    if engine["convert_wav_to_kurisu"] is None:
        raise HTTPException(status_code=501, detail="WAV conversion is not implemented for the GPT-SoVITS HTTP backend.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(file)
        tmp_path = tmp.name

    try:
        audio_bytes = engine["convert_wav_to_kurisu"](tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not audio_bytes:
        raise HTTPException(status_code=500, detail="Voice conversion failed")

    return Response(content=audio_bytes, media_type="audio/wav")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    port = int(os.environ.get("VOICE_API_PORT", "8767"))
    logger.info("Starting Kurisu Voice Clone API on port %s", port)
    print("Set ASSISTANT_TTS_PROVIDER=http, " f"ASSISTANT_TTS_ENDPOINT=http://127.0.0.1:{port}/tts, " "ASSISTANT_TTS_VOICE=kurisu_ja")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
