"""Quick test for Edge TTS voice."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ASSISTANT_TTS_PROVIDER"] = "edge-tts"
os.environ["ASSISTANT_TTS_VOICE"] = "ja-JP-NanamiNeural"

from src.assistant_app.voice import VoiceService


async def main():
    svc = VoiceService()
    print("Testing Edge TTS synthesize...")
    print("  Provider: edge-tts, Voice: ja-JP-NanamiNeural")
    result = await svc.synthesize(
        "こんにちは、私は牧瀬紅莉栖です。今日も研究に集中しましょう。",
        "normal",
    )
    print(f"  Engine: {result.engine}")
    print(f"  Audio URL: {result.audio_url}")
    print(f"  Reason: {result.reason}")

    if result.audio_url:
        audio_path = Path("../data/audio").resolve() / Path(result.audio_url).name
        file_size = audio_path.stat().st_size
        print(f"  Audio file: {audio_path}")
        print(f"  Audio file size: {file_size} bytes")
        if file_size > 1000:
            print("")
            print("✅ Edge TTS working! Audio file generated successfully.")
        else:
            print("  ⚠️ Audio file too small, might be empty.")
    else:
        print(f"  ❌ Edge TTS failed: {result.reason}")


if __name__ == "__main__":
    asyncio.run(main())