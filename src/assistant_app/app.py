from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .asr import AsrService
from .companion_seed import seed_original_companion_memories
from .memory import MemoryRecord, MemoryStore
from .providers.deepseek import DeepSeekClient
from .secret_store import SecretStore, SecretStoreError
from .settings import ROOT_DIR, STATIC_DIR, settings
from .soul import SoulEngine, SoulState, system_persona_prompt
from .tools.divergence import DivergenceMeter
from .tools.permissions import PermissionBroker
from .tools.research import ResearchSearch
from .voice import VoiceService
from .vtube import VTubeEvent, VTubeStudioClient


app = FastAPI(title="DeepSeek Desktop Research Companion", version="0.2.0")
settings.audio_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/audio", StaticFiles(directory=str(settings.audio_dir)), name="audio")
app.mount("/desktop-assets", StaticFiles(directory=str(ROOT_DIR / "desktop")), name="desktop-assets")

memory_store = MemoryStore()
seed_original_companion_memories(memory_store)
secret_store = SecretStore()
soul_engine = SoulEngine()
permission_broker = PermissionBroker()
vtube_client = VTubeStudioClient()
research_search = ResearchSearch()
divergence_meter = DivergenceMeter()
voice_service = VoiceService()
asr_service = AsrService()


class ChatRequest(BaseModel):
    text: str = Field(min_length=1)
    model: str | None = None
    source: str = "text"


class ChatResponse(BaseModel):
    ja_text: str
    zh_subtitle: str
    emotion: str
    gesture: str
    voice_style: str
    tool_intent: dict[str, Any]
    permission: dict[str, Any]
    soul_state: dict[str, Any]
    vtube: dict[str, Any] | None = None
    audio_url: str | None = None
    voice: dict[str, Any]


class KeyRequest(BaseModel):
    api_key: str = Field(min_length=8)


class MemoryCreateRequest(BaseModel):
    kind: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source: str = "manual"
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class ResearchSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=8, ge=1, le=25)


class CommandInspectRequest(BaseModel):
    command: str = Field(min_length=1)


class DivergenceNewsRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=10, ge=1, le=25)
    min_impact: float | None = None
    max_impact: float | None = None


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "fastapi",
        "model": settings.default_model,
        "secret": secret_store.status(),
        "db_path": str(settings.db_path),
        "voice": voice_service.status(),
        "asr": asr_service.status(),
    }


@app.post("/api/config/deepseek-key")
async def set_deepseek_key(request: KeyRequest) -> dict[str, bool]:
    try:
        secret_store.set_deepseek_key(request.api_key)
    except SecretStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"saved": True}


@app.get("/api/memories")
async def memories(q: str = "", limit: int = 20) -> list[dict[str, Any]]:
    rows = memory_store.search(q, limit=min(max(limit, 1), 100))
    return [dict(row) for row in rows]


@app.post("/api/memories")
async def add_memory(request: MemoryCreateRequest) -> dict[str, int]:
    memory_id = memory_store.add_memory(
        MemoryRecord(
            kind=request.kind,
            content=request.content,
            source=request.source,
            confidence=request.confidence,
        )
    )
    return {"id": memory_id}


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: int) -> dict[str, bool]:
    deleted = memory_store.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"deleted": True}


@app.post("/api/research/search")
async def search_research(request: ResearchSearchRequest) -> dict[str, Any]:
    try:
        papers = await research_search.search_arxiv(request.query, request.max_results)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"arXiv search failed: {exc}") from exc
    return {"papers": [paper.__dict__ for paper in papers]}


@app.post("/api/tools/inspect-command")
async def inspect_command(request: CommandInspectRequest) -> dict[str, Any]:
    return permission_broker.inspect_command(request.command).__dict__


@app.get("/api/tools/divergence")
async def get_divergence() -> dict[str, Any]:
    try:
        reading = await divergence_meter.current()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Divergence request failed: {exc}") from exc
    return reading.__dict__


@app.post("/api/tools/divergence/news")
async def get_divergence_news(request: DivergenceNewsRequest) -> dict[str, Any]:
    try:
        return await divergence_meter.news(
            page=request.page,
            per_page=request.per_page,
            min_impact=request.min_impact,
            max_impact=request.max_impact,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Divergence news request failed: {exc}") from exc


@app.get("/api/proactive/checkin")
async def proactive_checkin() -> dict[str, Any]:
    state = SoulState.from_dict(memory_store.get_state("soul", SoulState().to_dict()))
    latest = memory_store.latest_conversation()
    idle_minutes: float | None = None
    if latest:
        try:
            created_at = datetime.fromisoformat(str(latest["created_at"]))
            idle_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
        except ValueError:
            idle_minutes = None

    concern = state.vector.get("concern", 0.0)
    focus = state.vector.get("focus", 0.0)
    protectiveness = state.vector.get("protectiveness", 0.0)
    should_prompt = False
    ja_text = "準備はできているわ。"
    zh_subtitle = "准备好了。"
    emotion = "teasing_neutral"
    gesture = "idle"
    voice_style = "normal"

    if concern >= 0.48 or protectiveness >= 0.52 or state.work_mode == "care":
        should_prompt = True
        ja_text = "少し無理をしている気配があるわ。まず状況を一つずつ分解しましょう。"
        zh_subtitle = "我感觉你有点在硬撑。先把情况一项一项拆开。"
        emotion = "concerned_soft"
        gesture = "soft_eye_contact"
        voice_style = "soft"
    elif idle_minutes is not None and idle_minutes >= 120 and focus >= 0.62:
        should_prompt = True
        ja_text = "二時間以上空いたわね。研究を続けるなら、次の小さな作業から再開しなさい。"
        zh_subtitle = "已经空了两个多小时。如果要继续研究，就从下一个小任务恢复。"
        emotion = "focused"
        gesture = "point_to_task"
        voice_style = "serious"
    elif latest is None:
        should_prompt = True
        ja_text = "初回起動ね。まず研究テーマか今日片づけたい作業を渡しなさい。"
        zh_subtitle = "第一次启动。先把研究主题或今天要处理的任务交给我。"
        emotion = "thinking"
        gesture = "think"

    return {
        "should_prompt": should_prompt,
        "ja_text": ja_text,
        "zh_subtitle": zh_subtitle,
        "emotion": emotion,
        "gesture": gesture,
        "voice_style": voice_style,
        "idle_minutes": idle_minutes,
        "soul_state": state.to_dict(),
    }


@app.post("/api/asr/transcribe")
async def asr_transcribe(audio: UploadFile = File(...)) -> dict[str, Any]:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio payload is empty.")

    result = asr_service.transcribe_wav(audio_bytes, language="zh-CN")
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.reason or "ASR failed.")
    return {"text": result.text, "engine": result.engine}


@app.get("/api/voice/status")
async def voice_status() -> dict[str, Any]:
    return voice_service.status()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    api_key = secret_store.get_deepseek_key()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="DeepSeek API key is missing. Set it in the settings panel or DEEPSEEK_API_KEY.",
        )

    remembered_rows = memory_store.search(request.text, limit=8)
    remembered = [row["content"] for row in remembered_rows]
    state = SoulState.from_dict(memory_store.get_state("soul", SoulState().to_dict()))
    state = soul_engine.update(state, request.text)
    system_prompt = system_persona_prompt(state, remembered)

    client = DeepSeekClient(api_key=api_key)
    try:
        result = await client.chat_json(
            system_prompt=system_prompt,
            user_text=request.text,
            model=request.model or settings.default_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek request failed: {exc}") from exc

    parsed = _normalize_reply(result.parsed)
    state.emotion = parsed["emotion"]
    state.task_state = "waiting_confirmation" if parsed["tool_intent"]["risk"] in {"L3", "L4"} else "waiting"
    memory_store.set_state("soul", state.to_dict())
    memory_store.log_conversation(
        request.text,
        parsed["ja_text"],
        parsed["zh_subtitle"],
        parsed["emotion"],
        parsed["gesture"],
    )

    for update in parsed["memory_update"]:
        confidence = float(update.get("confidence", 0.0))
        content = str(update.get("content", "")).strip()
        if content and confidence >= 0.55:
            memory_store.add_memory(
                MemoryRecord(
                    kind=str(update.get("kind", "relationship")),
                    content=content,
                    source=f"chat:{request.source}",
                    confidence=confidence,
                )
            )

    permission = permission_broker.inspect_tool_intent(parsed["tool_intent"]["risk"])
    voice_result = await voice_service.synthesize(parsed["ja_text"], parsed["voice_style"])
    vtube_status = await vtube_client.emit(
        VTubeEvent(
            emotion=parsed["emotion"],
            gesture=parsed["gesture"],
            voice_style=parsed["voice_style"],
        )
    )

    return ChatResponse(
        ja_text=parsed["ja_text"],
        zh_subtitle=parsed["zh_subtitle"],
        emotion=parsed["emotion"],
        gesture=parsed["gesture"],
        voice_style=parsed["voice_style"],
        tool_intent=parsed["tool_intent"],
        permission=permission.__dict__,
        soul_state=state.to_dict(),
        vtube=vtube_status,
        audio_url=voice_result.audio_url,
        voice=voice_result.__dict__,
    )


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
    import uvicorn

    os.environ.setdefault("PYTHONUTF8", "1")
    uvicorn.run(
        "assistant_app.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        factory=False,
    )


if __name__ == "__main__":
    main()
