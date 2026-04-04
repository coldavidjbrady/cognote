#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import get_settings
from backend.app.importer import embed_pending_notes, import_notes_file


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
def main() -> int:
    args = parse_args()
    jsonl_path = Path(args.jsonl).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    settings = get_settings()

    if not jsonl_path.exists():
        print(f"JSONL file not found: {jsonl_path}")
        return 2

    imported, changed, archived = import_notes_file(jsonl_path, db_path)
    print(f"Imported {imported} notes into {db_path}.")
    print(f"Changed or new notes: {changed}.")
    print(f"Archived missing notes: {archived}.")

    if not args.skip_embeddings:
        embedded = embed_pending_notes(db_path, settings, batch_size=args.embedding_batch_size)
        if not settings.openai_api_key:
            print("OPENAI_API_KEY is not set; skipping embeddings.")
        print(f"Embedded {embedded} notes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
