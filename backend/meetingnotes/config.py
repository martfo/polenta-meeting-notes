"""config.json schema and load/save.

The Hugging Face token never appears here. It lives in the macOS Keychain
(see meetingnotes.storage.keychain).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class Config(BaseModel):
    vault_path: str
    backend_port: int = 8765
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    embedding_model: str = "bge-m3"
    language: str = "en"
    match_threshold: float = 0.75
    veto_margin: float = 0.10
    audio_retention_days: int = 30
    ocr_enabled: bool = True
    log_level: str = "info"


def default_config(vault_path: Path | str) -> Config:
    return Config(vault_path=str(vault_path))


def load_config(path: Path) -> Config:
    return Config.model_validate(json.loads(path.read_text()))


def save_config(config: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
