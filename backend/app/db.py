from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id TEXT NOT NULL UNIQUE,
    account TEXT NOT NULL,
    folder TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    source_created_at TEXT NOT NULL DEFAULT '',
    source_modified_at TEXT NOT NULL DEFAULT '',
    created_at_iso TEXT,
    modified_at_iso TEXT,
    body_text TEXT NOT NULL DEFAULT '',
    body_html TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    embedding_status TEXT NOT NULL DEFAULT 'pending',
    embedding_updated_at TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0,
    archived_at TEXT,
    last_seen_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_folder ON notes(folder);
CREATE INDEX IF NOT EXISTS idx_notes_account ON notes(account);
CREATE INDEX IF NOT EXISTS idx_notes_modified_iso ON notes(modified_at_iso DESC);
CREATE INDEX IF NOT EXISTS idx_notes_imported_at ON notes(imported_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    note_id UNINDEXED,
    title,
    body_text,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS note_embeddings (
    note_id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#315c4a',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_notes (
    collection_id INTEGER NOT NULL,
    note_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (collection_id, note_id),
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS note_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_note_id INTEGER NOT NULL,
    target_note_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL DEFAULT 'related',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_note_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_note_id) REFERENCES notes(id) ON DELETE CASCADE,
    CONSTRAINT unique_link UNIQUE (source_note_id, target_note_id, relationship_type)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    ensure_notes_archive_columns(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notes_archived
        ON notes(is_archived, modified_at_iso DESC, imported_at DESC)
        """
    )
    rebuild_notes_fts(conn)
    conn.commit()


def ensure_notes_archive_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]: row for row in conn.execute("PRAGMA table_info(notes)").fetchall()
    }
    if "is_archived" not in columns:
        conn.execute("ALTER TABLE notes ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
    if "archived_at" not in columns:
        conn.execute("ALTER TABLE notes ADD COLUMN archived_at TEXT")
    if "last_seen_at" not in columns:
        conn.execute("ALTER TABLE notes ADD COLUMN last_seen_at TEXT")
    conn.execute(
        """
        UPDATE notes
        SET is_archived = COALESCE(is_archived, 0),
            last_seen_at = COALESCE(last_seen_at, imported_at)
        """
    )


def archive_filter_clause(
    alias: str,
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> str | None:
    archived_column = f"COALESCE({alias}.is_archived, 0)"
    if archived_only:
        return f"{archived_column} = 1"
    if include_archived:
        return None
    return f"{archived_column} = 0"


def rebuild_notes_fts(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'notes_fts'"
    ).fetchone()
    current_sql = (row["sql"] if row and row["sql"] else "").lower()

    if "content=''" in current_sql or "note_id unindexed" not in current_sql:
        conn.execute("DROP TABLE IF EXISTS notes_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE notes_fts USING fts5(
                note_id UNINDEXED,
                title,
                body_text,
                tokenize='porter unicode61'
            )
            """
        )

    has_indexed_rows = conn.execute("SELECT COUNT(*) AS count FROM notes_fts").fetchone()
    if has_indexed_rows and int(has_indexed_rows["count"]) > 0:
        return

    notes = conn.execute("SELECT id, title, body_text FROM notes").fetchall()
    conn.executemany(
        "INSERT INTO notes_fts(note_id, title, body_text) VALUES (?, ?, ?)",
        [(row["id"], row["title"], row["body_text"]) for row in notes],
    )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in rows if row is not None]


def parse_datetime(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    direct_attempts = (
        lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
    )
    for attempt in direct_attempts:
        try:
            return attempt(text).astimezone(timezone.utc).isoformat()
        except Exception:
            continue

    formats = (
        "%A, %B %d, %Y at %I:%M:%S %p",
        "%A, %B %d, %Y at %H:%M:%S",
        "%a %b %d %H:%M:%S %Y",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def note_fingerprint(payload: dict[str, Any]) -> str:
    base = {
        "title": payload.get("title", ""),
        "body_text": payload.get("body_text", ""),
        "body_html": payload.get("body_html", ""),
        "modified": payload.get("modified", ""),
        "folder": payload.get("folder", ""),
        "account": payload.get("account", ""),
    }
    return hashlib.sha256(
        json.dumps(base, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def note_embedding_input(note: dict[str, Any]) -> str:
    title = (note.get("title") or "").strip()
    body = (note.get("body_text") or "").strip()
    if title and body:
        combined = f"{title}\n\n{body}"
    else:
        combined = title or body
    return combined[:8000]


def upsert_note(conn: sqlite3.Connection, payload: dict[str, Any]) -> tuple[int, bool]:
    imported_at = utc_now()
    last_seen_at = imported_at
    fingerprint = note_fingerprint(payload)
    created_iso = parse_datetime(payload.get("created"))
    modified_iso = parse_datetime(payload.get("modified"))

    existing = conn.execute(
        "SELECT id, fingerprint FROM notes WHERE source_note_id = ?",
        (payload["id"],),
    ).fetchone()

    values = (
        payload["id"],
        payload.get("account", ""),
        payload.get("folder", ""),
        payload.get("title", ""),
        payload.get("created", ""),
        payload.get("modified", ""),
        created_iso,
        modified_iso,
        payload.get("body_text", ""),
        payload.get("body_html", ""),
        int(payload.get("word_count") or 0),
        int(payload.get("char_count") or 0),
        fingerprint,
        imported_at,
    )

    changed = existing is None or existing["fingerprint"] != fingerprint
    embedding_status = "pending" if changed else "ready"

    if existing is None:
        cursor = conn.execute(
            """
            INSERT INTO notes (
                source_note_id, account, folder, title,
                source_created_at, source_modified_at,
                created_at_iso, modified_at_iso,
                body_text, body_html, word_count, char_count,
                fingerprint, imported_at, embedding_status,
                is_archived, archived_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values + (embedding_status, 0, None, last_seen_at),
        )
        note_id = int(cursor.lastrowid)
    else:
        note_id = int(existing["id"])
        conn.execute(
            """
            UPDATE notes
            SET account = ?,
                folder = ?,
                title = ?,
                source_created_at = ?,
                source_modified_at = ?,
                created_at_iso = ?,
                modified_at_iso = ?,
                body_text = ?,
                body_html = ?,
                word_count = ?,
                char_count = ?,
                fingerprint = ?,
                imported_at = ?,
                embedding_status = ?,
                embedding_updated_at = CASE WHEN ? = 'pending' THEN NULL ELSE embedding_updated_at END,
                is_archived = 0,
                archived_at = NULL,
                last_seen_at = ?
            WHERE id = ?
            """,
            (
                payload.get("account", ""),
                payload.get("folder", ""),
                payload.get("title", ""),
                payload.get("created", ""),
                payload.get("modified", ""),
                created_iso,
                modified_iso,
                payload.get("body_text", ""),
                payload.get("body_html", ""),
                int(payload.get("word_count") or 0),
                int(payload.get("char_count") or 0),
                fingerprint,
                imported_at,
                embedding_status,
                embedding_status,
                last_seen_at,
                note_id,
            ),
        )
        if changed:
            conn.execute("DELETE FROM note_embeddings WHERE note_id = ?", (note_id,))

    conn.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
    conn.execute(
        "INSERT INTO notes_fts(note_id, title, body_text) VALUES (?, ?, ?)",
        (note_id, payload.get("title", ""), payload.get("body_text", "")),
    )
    conn.commit()
    return note_id, changed


def archive_missing_notes(
    conn: sqlite3.Connection,
    seen_source_note_ids: set[str],
    archived_at: str | None = None,
) -> int:
    archived_at = archived_at or utc_now()
    if seen_source_note_ids:
        placeholders = ", ".join("?" for _ in seen_source_note_ids)
        query = f"""
            UPDATE notes
            SET is_archived = 1,
                archived_at = COALESCE(archived_at, ?)
            WHERE COALESCE(is_archived, 0) = 0
              AND source_note_id NOT IN ({placeholders})
        """
        params: list[Any] = [archived_at, *sorted(seen_source_note_ids)]
    else:
        query = """
            UPDATE notes
            SET is_archived = 1,
                archived_at = COALESCE(archived_at, ?)
            WHERE COALESCE(is_archived, 0) = 0
        """
        params = [archived_at]

    cursor = conn.execute(query, tuple(params))
    archived_count = int(cursor.rowcount or 0)
    conn.commit()
    return archived_count


def fetch_pending_embeddings(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, body_text
        FROM notes
        WHERE embedding_status = 'pending'
          AND COALESCE(is_archived, 0) = 0
        ORDER BY imported_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return rows_to_dicts(rows)


def store_embedding(
    conn: sqlite3.Connection,
    note_id: int,
    model: str,
    vector: list[float],
) -> None:
    updated_at = utc_now()
    conn.execute(
        """
        INSERT INTO note_embeddings(note_id, model, dimensions, vector_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(note_id) DO UPDATE SET
            model = excluded.model,
            dimensions = excluded.dimensions,
            vector_json = excluded.vector_json,
            updated_at = excluded.updated_at
        """,
        (note_id, model, len(vector), json.dumps(vector), updated_at),
    )
    conn.execute(
        """
        UPDATE notes
        SET embedding_status = 'ready',
            embedding_updated_at = ?
        WHERE id = ?
        """,
        (updated_at, note_id),
    )
    conn.commit()


def count_embeddings(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM note_embeddings e
        JOIN notes n ON n.id = e.note_id
        WHERE COALESCE(n.is_archived, 0) = 0
        """
    ).fetchone()
    return int(row["count"]) if row else 0


def list_collections(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.name,
            c.description,
            c.color,
            c.created_at,
            COUNT(n.id) AS note_count
        FROM collections c
        LEFT JOIN collection_notes cn ON cn.collection_id = c.id
        LEFT JOIN notes n ON n.id = cn.note_id AND COALESCE(n.is_archived, 0) = 0
        GROUP BY c.id
        ORDER BY LOWER(c.name)
        """
    ).fetchall()
    return rows_to_dicts(rows)


def create_collection(
    conn: sqlite3.Connection,
    name: str,
    description: str = "",
    color: str = "#315c4a",
) -> dict[str, Any]:
    created_at = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO collections(name, description, color, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (name.strip(), description.strip(), color.strip() or "#315c4a", created_at),
    )
    conn.commit()
    collection_id = int(cursor.lastrowid)
    row = conn.execute(
        """
        SELECT id, name, description, color, created_at, 0 AS note_count
        FROM collections
        WHERE id = ?
        """,
        (collection_id,),
    ).fetchone()
    return row_to_dict(row) or {}


def add_note_to_collection(conn: sqlite3.Connection, collection_id: int, note_id: int) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO collection_notes(collection_id, note_id, created_at)
        VALUES (?, ?, ?)
        """,
        (collection_id, note_id, utc_now()),
    )
    conn.commit()


def remove_note_from_collection(conn: sqlite3.Connection, collection_id: int, note_id: int) -> None:
    conn.execute(
        "DELETE FROM collection_notes WHERE collection_id = ? AND note_id = ?",
        (collection_id, note_id),
    )
    conn.commit()


def create_note_link(
    conn: sqlite3.Connection,
    source_note_id: int,
    target_note_id: int,
    relationship_type: str = "related",
    note: str = "",
) -> dict[str, Any]:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO note_links(
            source_note_id,
            target_note_id,
            relationship_type,
            note,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_note_id, target_note_id, relationship_type, note.strip(), utc_now()),
    )
    conn.commit()
    if cursor.lastrowid:
        link_id = int(cursor.lastrowid)
    else:
        existing = conn.execute(
            """
            SELECT id
            FROM note_links
            WHERE source_note_id = ? AND target_note_id = ? AND relationship_type = ?
            """,
            (source_note_id, target_note_id, relationship_type),
        ).fetchone()
        link_id = int(existing["id"])
    row = conn.execute(
        """
        SELECT
            nl.id,
            nl.relationship_type,
            nl.note,
            nl.created_at,
            source.id AS source_id,
            source.title AS source_title,
            target.id AS target_id,
            target.title AS target_title,
            target.folder AS target_folder,
            target.account AS target_account,
            COALESCE(target.modified_at_iso, target.source_modified_at, target.imported_at) AS target_sort_date
        FROM note_links nl
        JOIN notes source ON source.id = nl.source_note_id
        JOIN notes target ON target.id = nl.target_note_id
        WHERE nl.id = ?
        """,
        (link_id,),
    ).fetchone()
    return row_to_dict(row) or {}


def delete_note_link(conn: sqlite3.Connection, link_id: int) -> None:
    conn.execute("DELETE FROM note_links WHERE id = ?", (link_id,))
    conn.commit()


def get_note_collections(conn: sqlite3.Connection, note_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.name,
            c.description,
            c.color,
            c.created_at
        FROM collections c
        JOIN collection_notes cn ON cn.collection_id = c.id
        WHERE cn.note_id = ?
        ORDER BY LOWER(c.name)
        """,
        (note_id,),
    ).fetchall()
    return rows_to_dicts(rows)


def get_manual_links(conn: sqlite3.Connection, note_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            nl.id,
            nl.relationship_type,
            nl.note,
            nl.created_at,
            linked.id AS note_id,
            linked.title,
            linked.folder,
            linked.account,
            linked.source_modified_at AS modified_at_display,
            linked.modified_at_iso,
            COALESCE(linked.is_archived, 0) AS is_archived,
            linked.archived_at
        FROM note_links nl
        JOIN notes linked
            ON linked.id = CASE
                WHEN nl.source_note_id = ? THEN nl.target_note_id
                ELSE nl.source_note_id
            END
        WHERE nl.source_note_id = ? OR nl.target_note_id = ?
        ORDER BY nl.created_at DESC, LOWER(linked.title)
        """,
        (note_id, note_id, note_id),
    ).fetchall()
    return rows_to_dicts(rows)


def get_note(conn: sqlite3.Connection, note_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            id,
            source_note_id,
            account,
            folder,
            title,
            source_created_at AS created_at_display,
            source_modified_at AS modified_at_display,
            created_at_iso,
            modified_at_iso,
            body_text,
            word_count,
            char_count,
            embedding_status,
            imported_at,
            COALESCE(is_archived, 0) AS is_archived,
            archived_at,
            last_seen_at
        FROM notes
        WHERE id = ?
        """,
        (note_id,),
    ).fetchone()
    if row is None:
        return None

    note = row_to_dict(row) or {}
    note["collections"] = get_note_collections(conn, note_id)
    note["manual_links"] = get_manual_links(conn, note_id)
    return note


def get_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN COALESCE(is_archived, 0) = 0 THEN 1 ELSE 0 END), 0) AS total_notes,
            COUNT(DISTINCT CASE WHEN COALESCE(is_archived, 0) = 0 THEN account END) AS total_accounts,
            COUNT(DISTINCT CASE WHEN COALESCE(is_archived, 0) = 0 THEN folder END) AS total_folders,
            COALESCE(SUM(CASE WHEN COALESCE(is_archived, 0) = 0 THEN word_count ELSE 0 END), 0) AS total_words,
            COALESCE(SUM(CASE WHEN COALESCE(is_archived, 0) = 0 THEN char_count ELSE 0 END), 0) AS total_characters,
            COALESCE(SUM(CASE WHEN COALESCE(is_archived, 0) = 0 AND embedding_status = 'ready' THEN 1 ELSE 0 END), 0) AS notes_with_embeddings,
            COALESCE(SUM(CASE WHEN COALESCE(is_archived, 0) = 1 THEN 1 ELSE 0 END), 0) AS archived_notes
        FROM notes
        """
    ).fetchone()

    folders = conn.execute(
        """
        SELECT folder, COUNT(*) AS note_count
        FROM notes
        WHERE COALESCE(is_archived, 0) = 0
        GROUP BY folder
        ORDER BY note_count DESC, LOWER(folder)
        LIMIT 6
        """
    ).fetchall()

    overview = row_to_dict(counts) or {}
    overview["top_folders"] = rows_to_dicts(folders)
    overview["collections"] = list_collections(conn)
    return overview


def get_recent_notes(
    conn: sqlite3.Connection,
    limit: int = 20,
    collection_id: int | None = None,
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            n.id,
            n.title,
            n.folder,
            n.account,
            n.source_modified_at AS modified_at_display,
            n.modified_at_iso,
            substr(n.body_text, 1, 220) AS snippet,
            'recent' AS match_type,
            0.0 AS score
        FROM notes n
    """
    params: list[Any] = []
    clauses: list[str] = []
    archive_clause = archive_filter_clause(
        "n",
        include_archived=include_archived,
        archived_only=archived_only,
    )
    if archive_clause:
        clauses.append(archive_clause)
    if collection_id is not None:
        query += " JOIN collection_notes cn ON cn.note_id = n.id"
        clauses.append("cn.collection_id = ?")
        params.append(collection_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += """
        ORDER BY
            CASE WHEN n.modified_at_iso IS NULL THEN 1 ELSE 0 END,
            n.modified_at_iso DESC,
            n.imported_at DESC
        LIMIT ?
    """
    params.append(limit)
    rows = conn.execute(query, tuple(params)).fetchall()
    return rows_to_dicts(rows)


def list_notes(
    conn: sqlite3.Connection,
    collection_id: int | None = None,
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            n.id,
            n.title,
            n.folder,
            n.account,
            n.is_archived,
            n.archived_at,
            n.source_modified_at AS modified_at_display,
            n.modified_at_iso,
            substr(n.body_text, 1, 220) AS snippet,
            'library' AS match_type,
            0.0 AS score
        FROM notes n
    """
    params: list[Any] = []
    clauses: list[str] = []
    archive_clause = archive_filter_clause(
        "n",
        include_archived=include_archived,
        archived_only=archived_only,
    )
    if archive_clause:
        clauses.append(archive_clause)
    if collection_id is not None:
        query += " JOIN collection_notes cn ON cn.note_id = n.id"
        clauses.append("cn.collection_id = ?")
        params.append(collection_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += """
        ORDER BY
            CASE WHEN n.modified_at_iso IS NULL THEN 1 ELSE 0 END,
            n.modified_at_iso DESC,
            n.imported_at DESC
    """
    rows = conn.execute(query, tuple(params)).fetchall()
    return rows_to_dicts(rows)


def list_notes_by_date_range(
    conn: sqlite3.Connection,
    start_iso: str | None = None,
    end_iso: str | None = None,
    date_fields: tuple[str, ...] = ("created_at_iso", "modified_at_iso"),
    collection_id: int | None = None,
    limit: int | None = None,
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[dict[str, Any]]:
    supported_fields = {
        "created_at_iso": "n.created_at_iso",
        "modified_at_iso": "n.modified_at_iso",
    }
    active_fields = [supported_fields[field] for field in date_fields if field in supported_fields]
    if not active_fields:
        active_fields = [supported_fields["created_at_iso"], supported_fields["modified_at_iso"]]

    comparator_clauses = []
    params: list[Any] = []
    for field in active_fields:
        field_clauses = []
        if start_iso is not None:
            field_clauses.append(f"{field} >= ?")
            params.append(start_iso)
        if end_iso is not None:
            field_clauses.append(f"{field} < ?")
            params.append(end_iso)
        if field_clauses:
            comparator_clauses.append(f"({' AND '.join(field_clauses)})")

    if not comparator_clauses:
        return []

    query = """
        SELECT
            n.id,
            n.title,
            n.folder,
            n.account,
            n.is_archived,
            n.archived_at,
            n.source_modified_at AS modified_at_display,
            n.modified_at_iso,
            n.source_created_at AS created_at_display,
            n.created_at_iso,
            substr(n.body_text, 1, 220) AS snippet,
            'date' AS match_type,
            0.0 AS score
        FROM notes n
    """

    where_clauses = [f"({' OR '.join(comparator_clauses)})"]
    archive_clause = archive_filter_clause(
        "n",
        include_archived=include_archived,
        archived_only=archived_only,
    )
    if archive_clause:
        where_clauses.append(archive_clause)
    if collection_id is not None:
        query += " JOIN collection_notes cn ON cn.note_id = n.id"
        where_clauses.append("cn.collection_id = ?")
        params.append(collection_id)

    query += " WHERE " + " AND ".join(where_clauses)
    query += """
        ORDER BY
            COALESCE(n.modified_at_iso, n.created_at_iso, n.imported_at) DESC,
            LOWER(n.title)
    """
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, tuple(params)).fetchall()
    return rows_to_dicts(rows)


def keyword_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    collection_id: int | None = None,
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[dict[str, Any]]:
    search_sql = """
        SELECT
            n.id,
            n.title,
            n.folder,
            n.account,
            n.is_archived,
            n.archived_at,
            n.source_modified_at AS modified_at_display,
            n.modified_at_iso,
            COALESCE(
                NULLIF(snippet(notes_fts, 1, '[[mark]]', '[[/mark]]', ' ... ', 24), ''),
                substr(n.body_text, 1, 220)
            ) AS snippet,
            bm25(notes_fts) AS raw_score
        FROM notes_fts
        JOIN notes n ON n.id = notes_fts.note_id
    """
    params: list[Any] = []

    if collection_id is not None:
        search_sql += " JOIN collection_notes cn ON cn.note_id = n.id"

    clauses = ["notes_fts MATCH ?"]
    params.append(query)

    archive_clause = archive_filter_clause(
        "n",
        include_archived=include_archived,
        archived_only=archived_only,
    )
    if archive_clause:
        clauses.append(archive_clause)

    if collection_id is not None:
        clauses.append("cn.collection_id = ?")
        params.append(collection_id)

    search_sql += " WHERE " + " AND ".join(clauses)
    search_sql += " ORDER BY raw_score LIMIT ?"
    params.append(limit)

    rows = conn.execute(search_sql, tuple(params)).fetchall()
    return rows_to_dicts(rows)


def get_note_embedding(conn: sqlite3.Connection, note_id: int) -> list[float] | None:
    row = conn.execute(
        "SELECT vector_json FROM note_embeddings WHERE note_id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["vector_json"])


def get_embeddings(
    conn: sqlite3.Connection,
    collection_id: int | None = None,
    exclude_note_id: int | None = None,
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            n.id,
            n.title,
            n.folder,
            n.account,
            n.is_archived,
            n.archived_at,
            n.source_modified_at AS modified_at_display,
            n.modified_at_iso,
            substr(n.body_text, 1, 220) AS snippet,
            e.vector_json
        FROM note_embeddings e
        JOIN notes n ON n.id = e.note_id
    """
    clauses: list[str] = []
    params: list[Any] = []
    archive_clause = archive_filter_clause(
        "n",
        include_archived=include_archived,
        archived_only=archived_only,
    )
    if archive_clause:
        clauses.append(archive_clause)

    if collection_id is not None:
        query += " JOIN collection_notes cn ON cn.note_id = n.id"
        clauses.append("cn.collection_id = ?")
        params.append(collection_id)
    if exclude_note_id is not None:
        clauses.append("n.id != ?")
        params.append(exclude_note_id)

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    rows = conn.execute(query, tuple(params)).fetchall()
    items = rows_to_dicts(rows)
    for item in items:
        item["vector"] = json.loads(item.pop("vector_json"))
    return items
