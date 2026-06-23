# Amadeus Reference Usage

Source reviewed: `D:\download\Amadeus-main`

## Usable As Engineering Reference

- Modular assistant architecture: LLM, avatar, STT, TTS, memory, translation, and tools should remain replaceable components.
- VTube/Live2D direction: desktop pet should eventually drive expressions, motions, idle state, speaking state, and semantic gestures.
- TTS/ASR direction: browser speech should be treated as a temporary fallback; production should use a backend voice pipeline.
- Memory direction: long-term user interaction memory should be retrieved into the prompt and should influence tone, concern, and research continuity.
- Extension idea: a "Divergence Meter" style tool can be implemented as an original local tool integration.

## Not Usable Directly

- `Dialogues/SG_Dialogues_EN.md` and `Dialogues/emails.json`: do not ingest original scripts or emails as memory for direct character replication.
- `Voices/OneShot/*.wav`: do not use these files for voice cloning or matching a specific voice actor.
- `Prompts/Kurisu_EN.md` and `Prompts/Story_EN.md`: do not copy the official-character prompt or story memory into the app.
- Download links for official-like Live2D/LivePNG character models should not be used as the final identity of this project.

## Implementation Rule

Use the reference project to guide product shape, not identity replication. The app should remain an original Japanese-speaking research partner with Chinese subtitles, strong memory, active care, and research tooling.
