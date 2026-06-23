# Voice Pipeline

The app now supports a backend TTS handoff for Japanese speech.

## Current Behavior

- `/api/chat` always returns `ja_text` and `zh_subtitle`.
- If backend TTS is configured, `/api/chat` also returns `audio_url`.
- The workbench plays `audio_url` first and uses browser SpeechSynthesis only as fallback.

## Configure HTTP TTS

Set these environment variables before starting the backend:

```powershell
$env:ASSISTANT_TTS_PROVIDER = "http"
$env:ASSISTANT_TTS_ENDPOINT = "http://127.0.0.1:7860/tts"
$env:ASSISTANT_TTS_VOICE = "cold_researcher_ja"
.\scripts\run_backend.ps1
```

The endpoint should accept:

```json
{
  "text": "Japanese text",
  "language": "ja-JP",
  "voice": "cold_researcher_ja",
  "style": "normal|soft|serious|teasing"
}
```

It can return one of these:

- raw audio bytes with an `audio/*` content type
- JSON with `{ "audio_url": "http://..." }`
- JSON with `{ "audio_base64": "...", "format": "wav" }`

## Voice Direction

Target voice quality: cold, restrained, realistic, natural Japanese female researcher voice. Do not clone a specific voice actor or official character voice. Use an original or properly licensed voice.
