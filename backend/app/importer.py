from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterable

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


def import_notes_lines_with_progress(
    lines: Iterable[str],
    db_path: Path,
    *,
    progress_callback: Callable[[int], None] | None = None,
    progress_every: int = 100,
    note_error_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, int, int]:
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
                if note_error_callback:
                    note_error_callback(
                        {
                            "line_number": line_number,
                            "note_id": None,
                            "title": None,
                            "error": f"Invalid JSONL on line {line_number}: {exc.msg}",
                            "raw_excerpt": line.strip()[:500],
                        }
                    )
                continue

            try:
                source_note_id = str(payload["id"])
                seen_source_note_ids.add(source_note_id)
                _, did_change = upsert_note(conn, payload)
                imported += 1
                if did_change:
                    changed += 1
            except (KeyError, TypeError, ValueError, sqlite3.IntegrityError) as exc:
                if note_error_callback:
                    note_error_callback(
                        {
                            "line_number": line_number,
                            "note_id": str(payload.get("id") or ""),
                            "title": str(payload.get("title") or ""),
                            "error": str(exc),
                            "raw_excerpt": json.dumps(payload, ensure_ascii=False)[:500],
                        }
                    )
                continue

            if progress_callback and progress_every > 0 and imported % progress_every == 0:
                progress_callback(imported)

        archived = archive_missing_notes(conn, seen_source_note_ids)
        if progress_callback:
            progress_callback(imported)
    finally:
        conn.close()

    return imported, changed, archived


def import_notes_lines(
    lines: Iterable[str],
    db_path: Path,
    *,
    progress_callback: Callable[[int], None] | None = None,
    progress_every: int = 100,
    note_error_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, int, int]:
    return import_notes_lines_with_progress(
        lines,
        db_path,
        progress_callback=progress_callback,
        progress_every=progress_every,
        note_error_callback=note_error_callback,
    )


def import_notes_file(
    jsonl_path: Path,
    db_path: Path,
    *,
    progress_callback: Callable[[int], None] | None = None,
    progress_every: int = 100,
    note_error_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, int, int]:
    with jsonl_path.open("r", encoding="utf-8") as handle:
        return import_notes_lines_with_progress(
            handle,
            db_path,
            progress_callback=progress_callback,
            progress_every=progress_every,
            note_error_callback=note_error_callback,
        )


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
