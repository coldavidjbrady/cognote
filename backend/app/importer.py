from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .config import Settings
from .db import (
    archive_missing_notes,
    connect,
    fetch_pending_embeddings,
    init_db,
    note_embedding_input,
    store_embedding,
    upsert_note,
)
from .embeddings import EmbeddingService


def import_notes_lines(lines: Iterable[str], db_path: Path) -> tuple[int, int, int]:
    conn = connect(db_path)
    init_db(conn)
    imported = 0
    changed = 0
    seen_source_note_ids: set[str] = set()

    try:
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL on line {line_number}: {exc.msg}") from exc
            source_note_id = str(payload["id"])
            seen_source_note_ids.add(source_note_id)
            _, did_change = upsert_note(conn, payload)
            imported += 1
            if did_change:
                changed += 1

        archived = archive_missing_notes(conn, seen_source_note_ids)
    finally:
        conn.close()

    return imported, changed, archived


def import_notes_file(jsonl_path: Path, db_path: Path) -> tuple[int, int, int]:
    with jsonl_path.open("r", encoding="utf-8") as handle:
        return import_notes_lines(handle, db_path)


def embed_pending_notes(
    db_path: Path,
    settings: Settings,
    batch_size: int | None = None,
) -> int:
    service = EmbeddingService(settings)
    if not service.enabled:
        return 0

    conn = connect(db_path)
    init_db(conn)
    embedded = 0
    effective_batch_size = batch_size or settings.embedding_batch_size

    try:
        while True:
            batch = fetch_pending_embeddings(conn, limit=effective_batch_size)
            if not batch:
                break
            texts = [note_embedding_input(note) for note in batch]
            vectors = service.embed_texts(texts)
            for note, vector in zip(batch, vectors):
                store_embedding(conn, int(note["id"]), service.model, vector)
                embedded += 1
    finally:
        conn.close()

    return embedded
