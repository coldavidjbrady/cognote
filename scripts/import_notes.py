#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import get_settings
from backend.app.importer import import_notes_file
from backend.app.db import (
    connect,
    fetch_pending_embeddings,
    init_db,
    note_embedding_input,
    store_embedding,
)
from backend.app.embeddings import EmbeddingService


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Import Apple Notes JSONL into SQLite.")
    parser.add_argument(
        "--jsonl",
        default="notes_export.jsonl",
        help="Path to the JSONL file produced by apple_notes_exporter_v4.py",
    )
    parser.add_argument(
        "--db",
        default=str(settings.db_path),
        help="Target SQLite database path",
    )
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Import notes without requesting embeddings",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=50,
        help="How many pending notes to embed per batch",
    )
    return parser.parse_args()

def embed_pending_notes(db_path: Path, batch_size: int) -> int:
    settings = get_settings()
    service = EmbeddingService(settings)
    if not service.enabled:
        print("OPENAI_API_KEY is not set; skipping embeddings.")
        return 0

    conn = connect(db_path)
    init_db(conn)
    embedded = 0

    while True:
        batch = fetch_pending_embeddings(conn, limit=batch_size)
        if not batch:
            break
        texts = [note_embedding_input(note) for note in batch]
        vectors = service.embed_texts(texts)
        for note, vector in zip(batch, vectors):
            store_embedding(conn, int(note["id"]), service.model, vector)
            embedded += 1

    conn.close()
    return embedded


def main() -> int:
    args = parse_args()
    jsonl_path = Path(args.jsonl).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()

    if not jsonl_path.exists():
        print(f"JSONL file not found: {jsonl_path}")
        return 2

    imported, changed, archived = import_notes_file(jsonl_path, db_path)
    print(f"Imported {imported} notes into {db_path}.")
    print(f"Changed or new notes: {changed}.")
    print(f"Archived missing notes: {archived}.")

    if not args.skip_embeddings:
        embedded = embed_pending_notes(db_path, batch_size=args.embedding_batch_size)
        print(f"Embedded {embedded} notes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
