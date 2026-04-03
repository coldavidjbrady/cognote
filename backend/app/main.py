from __future__ import annotations

from contextlib import closing
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
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
from .llm import LLMService
from .schemas import AssistantQuery, CollectionCreate, CollectionNoteAdd, NoteLinkCreate
from .search import cosine_similarity, hybrid_search, related_notes


settings = get_settings()
embedding_service = EmbeddingService(settings)
llm_service = LLMService(settings)
app = FastAPI(title="Apple Notes Search API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
            "openai_enabled": embedding_service.enabled,
            "embeddings_indexed": count_embeddings(conn),
        }


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
) -> dict[str, object]:
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
        )
        return {
            "query": q,
            "mode": mode,
            "count": len(results),
            "results": results,
        }


@app.get("/api/notes")
def notes(collection_id: int | None = Query(default=None)) -> dict[str, object]:
    with closing(connect(settings.db_path)) as conn:
        init_db(conn)
        results = list_notes(conn, collection_id=collection_id)
        return {
            "count": len(results),
            "results": results,
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
