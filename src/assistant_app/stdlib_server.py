from __future__ import annotations

import json
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .companion_seed import seed_original_companion_memories
from .memory import MemoryRecord, MemoryStore
from .secret_store import SecretStore, SecretStoreError
from .settings import STATIC_DIR, settings
from .soul import SoulEngine, SoulState, system_persona_prompt
from .tools.permissions import PermissionBroker


memory_store = MemoryStore()
seed_original_companion_memories(memory_store)
secret_store = SecretStore()
soul_engine = SoulEngine()
permission_broker = PermissionBroker()


class MissingKeyError(RuntimeError):
    pass


class Handler(BaseHTTPRequestHandler):
    server_version = "ResearchCompanionStdlib/0.1"

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if self.path.startswith("/static/"):
            relative = self.path.removeprefix("/static/").split("?", 1)[0]
            self._send_static(relative)
            return
        if self.path.startswith("/api/health"):
            self._send_json(
                {
                    "ok": True,
                    "mode": "stdlib",
                    "model": settings.default_model,
                    "secret": secret_store.status(),
                    "db_path": str(settings.db_path),
                }
            )
            return
        if self.path.startswith("/api/memories"):
            rows = memory_store.search("", limit=20)
            self._send_json([dict(row) for row in rows])
            return
        self._send_json({"detail": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/config/deepseek-key":
            payload = self._read_json()
            try:
                secret_store.set_deepseek_key(str(payload.get("api_key", "")))
            except SecretStoreError as exc:
                self._send_json({"detail": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"saved": True})
            return
        if self.path == "/api/chat":
            payload = self._read_json()
            text = str(payload.get("text", "")).strip()
            if not text:
                self._send_json({"detail": "text is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                response = handle_chat(text, str(payload.get("source", "text")))
            except MissingKeyError as exc:
                self._send_json({"detail": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
                return
            except Exception as exc:
                self._send_json({"detail": f"DeepSeek request failed: {exc}"}, status=HTTPStatus.BAD_GATEWAY)
                return
            self._send_json(response)
            return
        self._send_json({"detail": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, relative: str) -> None:
        safe_name = Path(relative).name
        path = STATIC_DIR / safe_name
        if not path.exists():
            self._send_json({"detail": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        content_type = "application/octet-stream"
        if path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        if path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        self._send_file(path, content_type)


def handle_chat(text: str, source: str) -> dict[str, Any]:
    api_key = secret_store.get_deepseek_key()
    if not api_key:
        raise MissingKeyError(
            "DeepSeek API key is missing. Set it in the settings panel or DEEPSEEK_API_KEY."
        )
    remembered_rows = memory_store.search(text, limit=8)
    remembered = [row["content"] for row in remembered_rows]
    state = SoulState.from_dict(memory_store.get_state("soul", SoulState().to_dict()))
    state = soul_engine.update(state, text)
    parsed = _deepseek_chat(
        api_key,
        system_persona_prompt(state, remembered),
        text,
        settings.default_model,
    )
    parsed = _normalize_reply(parsed)
    state.emotion = parsed["emotion"]
    state.task_state = (
        "waiting_confirmation" if parsed["tool_intent"]["risk"] in {"L3", "L4"} else "waiting"
    )
    memory_store.set_state("soul", state.to_dict())
    memory_store.log_conversation(
        text, parsed["ja_text"], parsed["zh_subtitle"], parsed["emotion"], parsed["gesture"]
    )
    for update in parsed["memory_update"]:
        confidence = float(update.get("confidence", 0.0))
        content = str(update.get("content", "")).strip()
        if content and confidence >= 0.55:
            memory_store.add_memory(
                MemoryRecord(
                    kind=str(update.get("kind", "relationship")),
                    content=content,
                    source=f"chat:{source}",
                    confidence=confidence,
                )
            )
    permission = permission_broker.inspect_tool_intent(parsed["tool_intent"]["risk"])
    return {
        **parsed,
        "permission": permission.__dict__,
        "soul_state": state.to_dict(),
        "vtube": {"connected": False, "reason": "stdlib mode does not include websockets"},
    }


def _deepseek_chat(api_key: str, system_prompt: str, user_text: str, model: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        f"{settings.deepseek_base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return _parse_json(data["choices"][0]["message"]["content"])


def _parse_json(raw_text: str) -> dict[str, Any]:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw_text[start : end + 1])
        raise


def _normalize_reply(data: dict[str, Any]) -> dict[str, Any]:
    tool_intent = data.get("tool_intent") or {}
    return {
        "ja_text": str(data.get("ja_text") or "……応答の生成に失敗したわ。もう一度試して。"),
        "zh_subtitle": str(data.get("zh_subtitle") or "……回复生成失败了。再试一次。"),
        "emotion": str(data.get("emotion") or "thinking"),
        "gesture": str(data.get("gesture") or "think"),
        "voice_style": str(data.get("voice_style") or "normal"),
        "memory_update": data.get("memory_update") if isinstance(data.get("memory_update"), list) else [],
        "tool_intent": {
            "risk": str(tool_intent.get("risk") or "L0"),
            "description": str(tool_intent.get("description") or ""),
        },
    }


def main() -> None:
    server = ThreadingHTTPServer((settings.host, settings.port), Handler)
    print(f"Research companion running at http://{settings.host}:{settings.port}")
    print("FastAPI is not installed; running stdlib fallback server.")
    server.serve_forever()
