from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryRecord:
    kind: str
    content: str
    source: str = "chat"
    confidence: float = 0.8
    metadata: dict[str, Any] | None = None


class MemoryStore:
    def __init__(self, db_path: Path = settings.db_path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_text TEXT NOT NULL,
                    ja_text TEXT NOT NULL,
                    zh_subtitle TEXT NOT NULL,
                    emotion TEXT NOT NULL,
                    gesture TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS soul_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def add_memory(self, record: MemoryRecord) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO memories
                    (kind, content, source, confidence, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.kind,
                    record.content,
                    record.source,
                    record.confidence,
                    json.dumps(record.metadata or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
            return int(cur.lastrowid)

    def delete_memory(self, memory_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            return cur.rowcount == 1

    def search(self, query: str, limit: int = 8) -> list[sqlite3.Row]:
        terms = [term for term in query.lower().split() if len(term) >= 2]
        with self.connect() as conn:
            if not terms:
                rows = conn.execute(
                    "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                pattern = "%" + "%".join(terms[:4]) + "%"
                rows = conn.execute(
                    """
                    SELECT * FROM memories
                    WHERE lower(content) LIKE ?
                    ORDER BY confidence DESC, id DESC
                    LIMIT ?
                    """,
                    (pattern, limit),
                ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE memories SET last_used_at = ? WHERE id = ?",
                    (utc_now(), row["id"]),
                )
            return rows

    def log_conversation(
        self, user_text: str, ja_text: str, zh_subtitle: str, emotion: str, gesture: str
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations
                    (user_text, ja_text, zh_subtitle, emotion, gesture, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_text, ja_text, zh_subtitle, emotion, gesture, utc_now()),
            )

    def latest_conversation(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM conversations
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
    def get_state(self, key: str, default: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM soul_state WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return dict(default)
        return json.loads(row["value_json"])

    def set_state(self, key: str, value: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO soul_state (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), utc_now()),
            )

