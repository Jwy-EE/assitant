from __future__ import annotations

from pathlib import Path

from assistant_app.gpt_sovits import GPTSoVITSClient, GPTSoVITSConfig


def test_config_uses_repo_reference_files() -> None:
    cfg = GPTSoVITSConfig.from_env()
    assert cfg.ref_audio_path.name == "CRS_JP.wav"
    assert cfg.ref_text_path.name == "CRS_JP.wav.txt"
    assert cfg.tts_path == "/tts"


def test_validate_reports_missing_reference_files(tmp_path: Path) -> None:
    cfg = GPTSoVITSConfig(
        api_base="http://127.0.0.1:9880",
        tts_path="/tts",
        prompt_lang="ja",
        text_lang="ja",
        ref_audio_path=tmp_path / "missing.wav",
        ref_text_path=tmp_path / "missing.txt",
        text_split_method="cut5",
        batch_size=1,
        speed_factor=1.0,
        top_k=15,
        top_p=1.0,
        temperature=1.0,
        repetition_penalty=1.35,
        media_type="wav",
        streaming_mode=False,
        timeout_seconds=30.0,
    )
    issues = GPTSoVITSClient(cfg).validate()
    assert len(issues) == 2
    assert "reference audio not found" in issues[0]
    assert "reference text not found" in issues[1]


def test_env_override_changes_api_base(monkeypatch) -> None:
    monkeypatch.setenv("GPT_SOVITS_API_BASE", "http://127.0.0.1:7860")
    cfg = GPTSoVITSConfig.from_env()
    assert cfg.api_base == "http://127.0.0.1:7860"
