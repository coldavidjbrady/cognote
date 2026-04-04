from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import clear_settings_cache, get_settings
from .db import (
    add_note_to_collection,
    connect,
    count_embeddings,
    create_collection,
    create_note_link,
    delete_note_link,
    get_embeddings,
    get_note,
    list_notes,
    get_overview,
    init_db,
    list_collections,
    remove_note_from_collection,
)
from .embeddings import EmbeddingService
from .jobs import SyncJobManager
from .llm import LLMService
from .secrets import delete_openai_api_key, keychain_available, set_openai_api_key
from .schemas import (
    AssistantQuery,
    CollectionCreate,
    CollectionNoteAdd,
    NoteLinkCreate,
    OpenAIKeyUpdateRequest,
    SyncRunRequest,
)
from .search import cosine_similarity, hybrid_search, related_notes


settings = get_settings()
embedding_service = EmbeddingService(settings)
llm_service = LLMService(settings)
sync_job_manager = SyncJobManager(settings)
app = FastAPI(title="Apple Notes Search API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def refresh_runtime_state() -> None:
    global settings, embedding_service, llm_service, sync_job_manager
    clear_settings_cache()
    settings = get_settings()
    embedding_service = EmbeddingService(settings)
    llm_service = LLMService(settings)
    sync_job_manager = SyncJobManager(settings)


def current_settings_payload() -> dict[str, object]:
    return {
        "runtime_mode": settings.runtime_mode,
        "packaged_mode": settings.is_packaged,
        "semantic_search_enabled": embedding_service.enabled,
        "chat_enabled": llm_service.enabled,
        "openai_key_configured": bool(settings.openai_api_key),
        "openai_key_source": settings.openai_api_key_source,
        "keychain_available": keychain_available(),
        "can_manage_openai_key": settings.is_packaged and keychain_available(),
        "models": {
            "embedding": settings.openai_embedding_model,
            "chat": settings.openai_chat_model,
            "search": settings.openai_search_model,
        },
    }


def _frontend_ready() -> bool:
    return settings.frontend_dist_dir.is_dir() and (settings.frontend_dist_dir / "index.html").exists()


def _frontend_response(path: str = "") -> FileResponse | JSONResponse:
    if not _frontend_ready():
        return JSONResponse(
            {
                "detail": "Frontend build not found. Run `npm run build` in `frontend/` first.",
                "frontend_dist_dir": str(settings.frontend_dist_dir),
            },
            status_code=503,
        )

    dist_dir = settings.frontend_dist_dir.resolve()
    requested = path.lstrip("/")
    if not requested:
        return FileResponse(dist_dir / "index.html")

    candidate = (dist_dir / requested).resolve(strict=False)
    if candidate.is_file() and (candidate == dist_dir or dist_dir in candidate.parents):
        return FileResponse(candidate)

    return FileResponse(dist_dir / "index.html")


@app.on_event("startup")
def startup() -> None:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)


@app.get("/api/health")
def health() -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        return {
            "status": "ok",
            "db_path": str(settings.db_path),
            "runtime_mode": settings.runtime_mode,
            "frontend_dist_dir": str(settings.frontend_dist_dir),
            "exports_root_dir": str(settings.exports_root_dir),
            "frontend_ready": _frontend_ready(),
            "openai_enabled": embedding_service.enabled,
            "openai_key_source": settings.openai_api_key_source,
            "embeddings_indexed": count_embeddings(conn),
        }


@app.get("/api/settings")
def app_settings() -> dict[str, object]:
    return current_settings_payload()


@app.put("/api/settings/openai-key")
def update_openai_key(payload: OpenAIKeyUpdateRequest) -> dict[str, object]:
    if not settings.is_packaged:
        raise HTTPException(
            status_code=400,
            detail="OpenAI key management is only available in packaged mode. Use .env in dev mode.",
        )
    if not keychain_available():
        raise HTTPException(status_code=501, detail="macOS Keychain is not available on this system.")

    try:
        set_openai_api_key(payload.api_key)
        refresh_runtime_state()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return current_settings_payload()


@app.delete("/api/settings/openai-key")
def remove_openai_key() -> dict[str, object]:
    if not settings.is_packaged:
        raise HTTPException(
            status_code=400,
            detail="OpenAI key management is only available in packaged mode. Use .env in dev mode.",
        )
    if not keychain_available():
        raise HTTPException(status_code=501, detail="macOS Keychain is not available on this system.")

    try:
        delete_openai_api_key()
        refresh_runtime_state()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return current_settings_payload()


@app.get("/api/jobs/status")
def jobs_status() -> dict[str, object]:
    status = sync_job_manager.get_status()
    status["openai_enabled"] = embedding_service.enabled
    return status


@app.post("/api/jobs/setup")
def start_setup_job(payload: SyncRunRequest) -> dict[str, object]:
    try:
        return sync_job_manager.start_setup(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/jobs/sync")
def start_sync_job(payload: SyncRunRequest) -> dict[str, object]:
    try:
        return sync_job_manager.start_sync(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/overview")
def overview() -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        payload = get_overview(conn)
        payload["openai_enabled"] = embedding_service.enabled
        return payload


@app.get("/api/search")
def search(
    q: str = "",
    mode: str = Query(default="hybrid", pattern="^(hybrid|keyword|semantic)$"),
    limit: int = Query(default=20, ge=1, le=50),
    collection_id: int | None = Query(default=None),
    include_archived: bool = Query(default=False),
    archived_only: bool = Query(default=False),
) -> dict[str, object]:
    if archived_only:
        include_archived = True
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        results = hybrid_search(
            conn,
            settings,
            embedding_service,
            q,
            mode=mode,
            limit=limit,
            collection_id=collection_id,
            include_archived=include_archived,
            archived_only=archived_only,
        )
        return {
            "query": q,
            "mode": mode,
            "count": len(results),
            "results": results,
        }


@app.get("/api/notes")
def notes(
    collection_id: int | None = Query(default=None),
    include_archived: bool = Query(default=False),
    archived_only: bool = Query(default=False),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    if archived_only:
        include_archived = True
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        effective_limit = limit + 1 if limit is not None else None
        results = list_notes(
            conn,
            collection_id=collection_id,
            include_archived=include_archived,
            archived_only=archived_only,
            limit=effective_limit,
            offset=offset,
        )
        has_more = False
        next_offset = None
        if limit is not None and len(results) > limit:
            results = results[:limit]
            has_more = True
            next_offset = offset + len(results)
        return {
            "count": len(results),
            "results": results,
            "has_more": has_more,
            "next_offset": next_offset,
            "offset": offset,
            "limit": limit,
        }


@app.get("/api/notes/{note_id}")
def note_detail(note_id: int) -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        note = get_note(conn, note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return note


@app.get("/api/notes/{note_id}/related")
def note_related(note_id: int, limit: int = Query(default=6, ge=1, le=12)) -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        note = get_note(conn, note_id)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        items = related_notes(conn, note_id, limit=limit)
        return {"note_id": note_id, "count": len(items), "results": items}


@app.get("/api/collections")
def collections() -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        return {"collections": list_collections(conn)}


@app.post("/api/collections")
def create_collection_endpoint(payload: CollectionCreate) -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        try:
            collection = create_collection(conn, payload.name, payload.description, payload.color)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        for note_id in payload.note_ids:
            add_note_to_collection(conn, int(collection["id"]), note_id)

        return {"collection": collection}


@app.post("/api/collections/{collection_id}/notes")
def add_collection_note(collection_id: int, payload: CollectionNoteAdd) -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        add_note_to_collection(conn, collection_id, payload.note_id)
        return {"status": "ok"}


@app.delete("/api/collections/{collection_id}/notes/{note_id}")
def remove_collection_note(collection_id: int, note_id: int) -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        remove_note_from_collection(conn, collection_id, note_id)
        return {"status": "ok"}


@app.post("/api/links")
def create_link_endpoint(payload: NoteLinkCreate) -> dict[str, object]:
    if payload.source_note_id == payload.target_note_id:
        raise HTTPException(status_code=400, detail="A note cannot be linked to itself.")

    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        link = create_note_link(
            conn,
            payload.source_note_id,
            payload.target_note_id,
            payload.relationship_type,
            payload.note,
        )
        return {"link": link}


@app.delete("/api/links/{link_id}")
def delete_link_endpoint(link_id: int) -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        delete_note_link(conn, link_id)
        return {"status": "ok"}


def _format_note_context(
    note: dict[str, Any],
    label: str,
    *,
    char_limit: int,
    rationale: str | None = None,
) -> str:
    title = (note.get("title") or "Untitled note").strip()
    folder = (note.get("folder") or "Unknown folder").strip()
    body = (note.get("body_text") or "").strip()
    excerpt = body[:char_limit]
    section = (
        f"[{label}]\n"
        f"Title: {title}\n"
        f"Folder: {folder}\n"
        f"Body:\n{excerpt if excerpt else '(No visible plain text)'}"
    )
    if rationale:
        section = f"{section}\nReason included: {rationale}"
    return section


def _retrieve_semantic_context_notes(
    conn,
    question: str,
    exclude_note_ids: set[int],
    limit: int = 3,
) -> list[dict[str, object]]:
    if not embedding_service.enabled or not question.strip():
        return []

    query_vector = embedding_service.embed_text(question.strip())
    if not query_vector:
        return []

    scored: list[tuple[float, dict[str, object]]] = []
    for candidate in get_embeddings(conn):
        note_id = int(candidate["id"])
        if note_id in exclude_note_ids:
            continue
        similarity = cosine_similarity(query_vector, candidate["vector"])
        score = (similarity + 1) / 2
        if score < max(settings.semantic_min_score, 0.7):
            continue
        scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)

    retrieved_notes: list[dict[str, object]] = []
    for score, candidate in scored[:limit]:
        note = get_note(conn, int(candidate["id"]))
        if not note:
            continue
        retrieved_notes.append(
            {
                "id": note["id"],
                "title": note.get("title") or "Untitled note",
                "folder": note.get("folder") or "",
                "kind": "retrieved",
                "score": round(score, 3),
                "note": note,
            }
        )
    return retrieved_notes


def _assistant_context_notes(
    conn,
    question: str,
    note_id: int,
    include_linked_notes: bool,
) -> tuple[list[dict[str, object]], str]:
    note = get_note(conn, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    context_items: list[dict[str, object]] = [
        {
            "id": note["id"],
            "title": note.get("title") or "Untitled note",
            "folder": note.get("folder") or "",
            "kind": "selected",
        }
    ]
    context_blocks = [_format_note_context(note, "Selected note", char_limit=5000)]
    seen_note_ids = {int(note["id"])}

    if include_linked_notes:
        for linked in note.get("manual_links", []):
            linked_note_id = int(linked["note_id"])
            if linked_note_id in seen_note_ids:
                continue
            linked_note = get_note(conn, linked_note_id)
            if not linked_note:
                continue
            seen_note_ids.add(linked_note_id)
            context_items.append(
                {
                    "id": linked_note["id"],
                    "title": linked_note.get("title") or "Untitled note",
                    "folder": linked_note.get("folder") or "",
                    "kind": "linked",
                }
            )
            context_blocks.append(_format_note_context(linked_note, "Linked note", char_limit=2500))

    for retrieved in _retrieve_semantic_context_notes(conn, question, seen_note_ids):
        seen_note_ids.add(int(retrieved["id"]))
        retrieved_note = retrieved["note"]
        context_items.append(
            {
                "id": retrieved["id"],
                "title": retrieved["title"],
                "folder": retrieved["folder"],
                "kind": "retrieved",
                "score": retrieved["score"],
            }
        )
        context_blocks.append(
            _format_note_context(
                retrieved_note,
                "Retrieved relevant note",
                char_limit=1800,
                rationale=f"Semantic match score {retrieved['score']}",
            )
        )

    return context_items, "\n\n---\n\n".join(context_blocks)


@app.post("/api/assistant/query")
def assistant_query(payload: AssistantQuery) -> dict[str, object]:
    if not llm_service.enabled:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is required to use the assistant.",
        )

    context_notes: list[dict[str, object]] = []
    context_text = ""

    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        if payload.mode == "note":
            if payload.note_id is None:
                raise HTTPException(status_code=400, detail="note_id is required in note mode.")
            context_notes, context_text = _assistant_context_notes(
                conn,
                question=payload.question,
                note_id=payload.note_id,
                include_linked_notes=payload.include_linked_notes,
            )

    try:
        result = llm_service.answer_question(
            payload.question,
            mode=payload.mode,
            history=[item.model_dump() for item in payload.history],
            context_text=context_text,
            allow_web_search=True,
            previous_response_id=payload.previous_response_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Assistant request failed: {exc}") from exc

    return {
        "question": payload.question,
        "mode": payload.mode,
        "model": result.model,
        "response_id": result.response_id,
        "answer": result.answer,
        "used_note_context": bool(context_notes),
        "used_web_search": result.used_web_search,
        "web_sources": result.web_sources,
        "context_notes": context_notes,
    }


if settings.is_packaged:
    @app.get("/", include_in_schema=False)
    def frontend_root():
        return _frontend_response()


    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_catch_all(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return _frontend_response(full_path)
