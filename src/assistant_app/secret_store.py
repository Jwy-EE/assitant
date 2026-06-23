from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path
from typing import Any

from .settings import settings


class SecretStoreError(RuntimeError):
    pass


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> DATA_BLOB:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretStoreError("DPAPI secret storage is only available on Windows.")
    in_blob = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise SecretStoreError("CryptProtectData failed.")
    return _bytes_from_blob(out_blob)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretStoreError("DPAPI secret storage is only available on Windows.")
    in_blob = _blob_from_bytes(data)
    out_blob = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise SecretStoreError("CryptUnprotectData failed.")
    return _bytes_from_blob(out_blob)


class SecretStore:
    def __init__(self, path: Path = settings.secret_path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, bool]:
        return {
            "has_env_key": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "has_saved_key": self.path.exists(),
        }

    def get_deepseek_key(self) -> str | None:
        env_key = os.environ.get("DEEPSEEK_API_KEY")
        if env_key:
            return env_key
        if not self.path.exists():
            return None
        payload = json.loads(_unprotect(base64.b64decode(self.path.read_text("utf-8"))))
        key = payload.get("deepseek_api_key")
        return key if isinstance(key, str) and key else None

    def set_deepseek_key(self, key: str) -> None:
        key = key.strip()
        if not key:
            raise SecretStoreError("DeepSeek API key is empty.")
        payload: dict[str, Any] = {"deepseek_api_key": key}
        encrypted = base64.b64encode(_protect(json.dumps(payload).encode("utf-8")))
        self.path.write_text(encrypted.decode("ascii"), encoding="utf-8")

