"""
Voice Clone API Server
======================
HTTP server that provides TTS + voice conversion to sound like Kurisu Makise.
Compatible with the existing TTS pipeline (see docs/voice_pipeline.md).

Usage:
    set ASSISTANT_TTS_PROVIDER=http
    set ASSISTANT_TTS_ENDPOINT=http://127.0.0.1:8766/tts
    set ASSISTANT_TTS_VOICE=kurisu_ja
    python voice_api_server.py
"""

import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add src to path for project imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

app = FastAPI(title="Kurisu Voice Clone API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

# Lazy import voice engine
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        # Use the Kurisu Voice Final Engine (pyworld + STFT based on CRS_JP.wav F0 analysis)
        try:
            from kurisu_voice_final import (
                text_to_kurisu,
                convert_wav_to_kurisu,
            )
            # Simple GPU check
            def check_gpu():
                return {"cuda_available": False, "device": "cpu", "vram_mb": 0, "model": "pyworld+STFT"}
            
            _engine = {
                "check_gpu": check_gpu,
                "text_to_kurisu_voice": text_to_kurisu,
                "convert_wav_to_kurisu": convert_wav_to_kurisu,
                "engine": "kurisu_final",
            }
        except ImportError:
            from gpt_sovits_kurisu import text_to_kurisu, convert_wav_to_kurisu, check_gpu
            _engine = {
                "check_gpu": check_gpu,
                "text_to_kurisu_voice": text_to_kurisu,
                "convert_wav_to_kurisu": convert_wav_to_kurisu,
                "engine": "fallback",
            }
        logger.info(f"Voice engine initialized: {_engine['engine']}")
    return _engine


class TTSRequest(BaseModel):
    text: str
    language: str = "ja-JP"
    voice: str = "kurisu_ja"
    style: str = "normal"


class HealthResponse(BaseModel):
    status: str
    gpu: dict
    model_dir: str


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    engine = get_engine()
    gpu = engine["check_gpu"]()
    return HealthResponse(
        status="ok",
        gpu=gpu,
        model_dir=str(Path("D:/voice_clone_models").absolute()),
    )


@app.post("/tts")
async def tts(request: TTSRequest):
    """
    TTS endpoint compatible with voice_pipeline.md spec.
    
    Accepts:
        - text: Japanese/Chinese/English text to synthesize
        - language: Language code (ja-JP, zh-CN, en-US)
        - voice: Voice name (kurisu_ja, kurisu_zh, kurisu_en)
        - style: Speaking style (normal, soft, serious, teasing)
    
    Returns:
        WAV audio bytes with Kurisu's voice
    """
    engine = get_engine()
    
    # Map language code
    lang_map = {
        "ja-JP": "ja",
        "zh-CN": "zh",
        "en-US": "en",
    }
    lang = lang_map.get(request.language, "ja")
    
    logger.info(f"TTS request: text='{request.text[:50]}...' lang={lang} style={request.style}")
    
    # Synthesize voice (engine ignores lang, always generates Japanese Kurisu voice)
    audio_bytes = engine["text_to_kurisu_voice"](request.text)
    
    if audio_bytes is None:
        raise HTTPException(status_code=500, detail="Voice synthesis failed")
    
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "inline; filename=kurisu_output.wav",
        },
    )


class WavConversionResponse(BaseModel):
    audio_url: str
    format: str = "wav"


@app.post("/convert")
async def convert_wav(file: bytes):
    """
    Convert an uploaded WAV file to Kurisu's voice.
    Accepts raw WAV bytes in request body.
    """
    engine = get_engine()
    
    # Save uploaded file temporarily
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(file)
        tmp_path = tmp.name
    
    try:
        audio_bytes = engine["convert_wav_to_kurisu"](tmp_path)
        if audio_bytes is None:
            raise HTTPException(status_code=500, detail="Voice conversion failed")
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    port = int(os.environ.get("VOICE_API_PORT", 8766))
    logger.info(f"Starting Kurisu Voice Clone API on port {port}...")
    
    # Print usage instructions
    print("""
╔══════════════════════════════════════════════════════════════╗
║           Kurisu Makise Voice Clone API Server              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  To use in your assistant pipeline, set:                    ║
║                                                              ║
║    $env:ASSISTANT_TTS_PROVIDER = "http"                      ║
║    $env:ASSISTANT_TTS_ENDPOINT = "http://127.0.0.1:8766/tts" ║
║    $env:ASSISTANT_TTS_VOICE = "kurisu_ja"                    ║
║                                                              ║
║  Test: curl -X POST http://127.0.0.1:8766/tts               ║
║    -H "Content-Type: application/json"                      ║
║    -d '{"text":"こんにちは","language":"ja-JP"}'             ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
