from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .db import archive_missing_notes, connect, init_db, upsert_note


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
