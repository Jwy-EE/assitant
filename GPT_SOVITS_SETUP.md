# GPT-SoVITS Local Voice Setup

This repo now includes a GPT-SoVITS-first voice bridge:

- API server: `voice_api_server_v2.py`
- GPT-SoVITS client: `src/assistant_app/gpt_sovits.py`
- Launcher: `start_companion_gpt_sovits.cmd`
- Smoke test: `scripts/test_gpt_sovits_voice.py`

## Current behavior

`voice_api_server_v2.py` always tries GPT-SoVITS first.

It uses:

- reference audio: `Amadeus-main/Voices/OneShot/CRS_JP.wav`
- reference text: `Amadeus-main/Voices/OneShot/CRS_JP.wav.txt`

If the local GPT-SoVITS server is unavailable, it falls back to the existing
Kurisu signal-processing voice path and exposes the reason through
`GET /api/health`.

## Expected local GPT-SoVITS server

Default endpoint configuration:

- base URL: `http://127.0.0.1:9880`
- health: `GET /health`
- tts: `POST /tts`

Default JSON payload sent to `/tts`:

```json
{
  "text": "....",
  "text_lang": "ja",
  "ref_audio_path": "D:/.../CRS_JP.wav",
  "prompt_text": "....",
  "prompt_lang": "ja",
  "text_split_method": "cut0",
  "batch_size": 1,
  "speed_factor": 1.0,
  "top_k": 15,
  "top_p": 1.0,
  "temperature": 1.0,
  "repetition_penalty": 1.35,
  "media_type": "wav",
  "streaming_mode": false
}
```

This matches the common GPT-SoVITS HTTP style used by local API wrappers.

## Environment variables

Optional overrides:

```powershell
$env:VOICE_API_PORT = "8767"
$env:KURISU_VOICE_MODE = "auto"
$env:GPT_SOVITS_API_BASE = "http://127.0.0.1:9880"
$env:GPT_SOVITS_TTS_PATH = "/tts"
$env:GPT_SOVITS_HEALTH_PATH = "/health"
$env:GPT_SOVITS_REF_AUDIO = "D:\path\to\CRS_JP.wav"
$env:GPT_SOVITS_REF_TEXT = "D:\path\to\CRS_JP.wav.txt"
```

Force hard failure instead of fallback:

```powershell
$env:KURISU_VOICE_MODE = "gpt-sovits"
```

## Run order

1. Start your local GPT-SoVITS HTTP server on `127.0.0.1:9880`
2. Run `start_companion_gpt_sovits.cmd`
3. Check `http://127.0.0.1:8767/api/health`
4. Run:

```powershell
.venv\Scripts\python.exe scripts\test_gpt_sovits_voice.py
```

## What was verified in this repo

- `src/assistant_app/gpt_sovits.py` imports successfully
- `voice_api_server_v2.py` starts successfully
- `tests/test_gpt_sovits.py` passes
- `GET /api/health` correctly reports fallback when no GPT-SoVITS server is listening on `127.0.0.1:9880`
