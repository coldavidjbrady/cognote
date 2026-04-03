from __future__ import annotations

from contextlib import closing

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
    get_note,
    get_overview,
    init_db,
    list_collections,
    remove_note_from_collection,
)
from .embeddings import EmbeddingService
from .schemas import CollectionCreate, CollectionNoteAdd, NoteLinkCreate
from .search import hybrid_search, related_notes


settings = get_settings()
embedding_service = EmbeddingService(settings)
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
