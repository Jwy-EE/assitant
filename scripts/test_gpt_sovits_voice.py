from __future__ import annotations

import os
from pathlib import Path

import httpx


VOICE_API_PORT = int(os.environ.get("VOICE_API_PORT", "8767"))
BASE_URL = f"http://127.0.0.1:{VOICE_API_PORT}"


def main() -> None:
    out_dir = Path("data") / "voice_tests"
    out_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=120.0) as client:
        health = client.get(f"{BASE_URL}/api/health")
        health.raise_for_status()
        print("health:", health.json())

        payload = {
            "text": "これでようやく、まともな音色検証ができるわね。",
            "language": "ja-JP",
            "voice": "kurisu_ja",
            "style": "serious",
        }
        response = client.post(f"{BASE_URL}/tts", json=payload)
        response.raise_for_status()

    out_path = out_dir / "kurisu_gpt_sovits_test.wav"
    out_path.write_bytes(response.content)
    print(f"saved: {out_path} ({len(response.content)} bytes)")


if __name__ == "__main__":
    main()
