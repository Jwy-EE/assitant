from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    deepseek_base_url: str = "https://api.deepseek.com"
    default_model: str = "deepseek-v4-flash"
    pro_model: str = "deepseek-v4-pro"
    db_path: Path = DATA_DIR / "assistant.sqlite3"
    secret_path: Path = DATA_DIR / "secrets.dpapi"
    config_path: Path = DATA_DIR / "app_config.json"
    audio_dir: Path = DATA_DIR / "audio"
    vtube_url: str = "ws://127.0.0.1:8001"


settings = Settings()


