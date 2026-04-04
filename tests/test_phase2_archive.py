from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.db import (
    archive_missing_notes,
    connect,
    get_embeddings,
    get_note,
    get_recent_notes,
    init_db,
    keyword_search,
    list_notes,
    upsert_note,
)
from backend.app.importer import import_notes_file


def sample_note(source_id: str, title: str, body_text: str, *, folder: str = "Inbox") -> dict[str, object]:
    return {
        "id": source_id,
        "account": "iCloud",
        "folder": folder,
        "title": title,
        "created": "2024-01-01 10:00:00",
        "modified": "2024-01-02 10:00:00",
        "body_text": body_text,
        "body_html": f"<p>{body_text}</p>",
        "word_count": len(body_text.split()),
        "char_count": len(body_text),
    }


class ArchiveMigrationTests(unittest.TestCase):
    def test_init_db_adds_archive_columns_to_existing_notes_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "notes.db"
            conn = connect(db_path)
            conn.execute("DROP TABLE IF EXISTS notes")
            conn.execute(
                """
                CREATE TABLE notes (
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
                    embedding_updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO notes(
                    source_note_id, account, folder, title,
                    source_created_at, source_modified_at,
                    created_at_iso, modified_at_iso, body_text, body_html,
                    word_count, char_count, fingerprint, imported_at,
                    embedding_status, embedding_updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-1",
                    "iCloud",
                    "Inbox",
                    "Legacy Note",
                    "",
                    "",
                    None,
                    None,
                    "legacy body",
                    "<p>legacy body</p>",
                    2,
                    11,
                    "abc123",
                    "2024-01-01T00:00:00+00:00",
                    "ready",
                    None,
                ),
            )
            conn.commit()

            init_db(conn)

            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(notes)").fetchall()
            }
            self.assertIn("is_archived", columns)
            self.assertIn("archived_at", columns)
            self.assertIn("last_seen_at", columns)

            row = conn.execute(
                "SELECT is_archived, archived_at, last_seen_at, imported_at FROM notes WHERE source_note_id = ?",
                ("legacy-1",),
            ).fetchone()
            self.assertEqual(int(row["is_archived"]), 0)
            self.assertIsNone(row["archived_at"])
            self.assertEqual(row["last_seen_at"], row["imported_at"])
            conn.close()


class ArchiveSyncTests(unittest.TestCase):
    def test_archive_missing_notes_and_default_queries_hide_archived(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conn = connect(Path(temp_dir) / "notes.db")
            init_db(conn)

            note1_id, _ = upsert_note(conn, sample_note("note-1", "Recipe", "banana bread recipe"))
            note2_id, _ = upsert_note(conn, sample_note("note-2", "Travel", "paris packing list"))

            archived = archive_missing_notes(conn, {"note-1"})
            self.assertEqual(archived, 1)

            active_notes = list_notes(conn)
            archived_notes = list_notes(conn, archived_only=True)
            recent_notes = get_recent_notes(conn)
            keyword_active = keyword_search(conn, "paris", limit=10)
            keyword_archived = keyword_search(conn, "paris", limit=10, archived_only=True)

            self.assertEqual([note["id"] for note in active_notes], [note1_id])
            self.assertEqual([note["id"] for note in archived_notes], [note2_id])
            self.assertEqual([note["id"] for note in recent_notes], [note1_id])
            self.assertEqual(keyword_active, [])
            self.assertEqual([note["id"] for note in keyword_archived], [note2_id])

            archived_note = get_note(conn, note2_id)
            self.assertEqual(int(archived_note["is_archived"]), 1)
            self.assertIsNotNone(archived_note["archived_at"])
            conn.close()

    def test_import_file_archives_missing_notes_and_revives_returned_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "notes.db"
            first_import = Path(temp_dir) / "first.jsonl"
            second_import = Path(temp_dir) / "second.jsonl"
            third_import = Path(temp_dir) / "third.jsonl"

            first_import.write_text(
                "\n".join(
                    [
                        '{"id":"note-1","account":"iCloud","folder":"Inbox","title":"Recipe","created":"2024-01-01 10:00:00","modified":"2024-01-02 10:00:00","body_text":"banana bread recipe","body_html":"<p>banana bread recipe</p>","word_count":3,"char_count":19}',
                        '{"id":"note-2","account":"iCloud","folder":"Inbox","title":"Travel","created":"2024-01-01 10:00:00","modified":"2024-01-02 10:00:00","body_text":"paris packing list","body_html":"<p>paris packing list</p>","word_count":3,"char_count":18}',
                    ]
                ),
                encoding="utf-8",
            )
            second_import.write_text(
                '{"id":"note-1","account":"iCloud","folder":"Inbox","title":"Recipe","created":"2024-01-01 10:00:00","modified":"2024-01-02 10:00:00","body_text":"banana bread recipe","body_html":"<p>banana bread recipe</p>","word_count":3,"char_count":19}\n',
                encoding="utf-8",
            )
            third_import.write_text(
                "\n".join(
                    [
                        '{"id":"note-1","account":"iCloud","folder":"Inbox","title":"Recipe","created":"2024-01-01 10:00:00","modified":"2024-01-02 10:00:00","body_text":"banana bread recipe","body_html":"<p>banana bread recipe</p>","word_count":3,"char_count":19}',
                        '{"id":"note-2","account":"iCloud","folder":"Inbox","title":"Travel","created":"2024-01-01 10:00:00","modified":"2024-01-03 10:00:00","body_text":"paris packing list updated","body_html":"<p>paris packing list updated</p>","word_count":4,"char_count":26}',
                    ]
                ),
                encoding="utf-8",
            )

            imported, changed, archived = import_notes_file(first_import, db_path)
            self.assertEqual((imported, changed, archived), (2, 2, 0))

            imported, changed, archived = import_notes_file(second_import, db_path)
            self.assertEqual((imported, changed, archived), (1, 0, 1))

            conn = connect(db_path)
            init_db(conn)
            archived_note = conn.execute(
                "SELECT id, is_archived FROM notes WHERE source_note_id = 'note-2'"
            ).fetchone()
            note2_id = int(archived_note["id"])
            self.assertEqual(int(archived_note["is_archived"]), 1)
            conn.close()

            imported, changed, archived = import_notes_file(third_import, db_path)
            self.assertEqual((imported, changed, archived), (2, 1, 0))

            conn = connect(db_path)
            init_db(conn)
            revived_note = get_note(conn, note2_id)
            self.assertEqual(int(revived_note["is_archived"]), 0)
            self.assertIsNone(revived_note["archived_at"])
            self.assertIn(note2_id, [note["id"] for note in list_notes(conn)])
            conn.close()

    def test_archived_notes_are_excluded_from_embeddings_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            conn = connect(Path(temp_dir) / "notes.db")
            init_db(conn)
            note1_id, _ = upsert_note(conn, sample_note("note-1", "Recipe", "banana bread recipe"))
            note2_id, _ = upsert_note(conn, sample_note("note-2", "Travel", "paris packing list"))

            conn.execute(
                """
                INSERT INTO note_embeddings(note_id, model, dimensions, vector_json, updated_at)
                VALUES (?, 'test-model', 2, '[0.1, 0.2]', '2024-01-01T00:00:00+00:00')
                """,
                (note1_id,),
            )
            conn.execute(
                """
                INSERT INTO note_embeddings(note_id, model, dimensions, vector_json, updated_at)
                VALUES (?, 'test-model', 2, '[0.3, 0.4]', '2024-01-01T00:00:00+00:00')
                """,
                (note2_id,),
            )
            conn.commit()

            archive_missing_notes(conn, {"note-1"})

            active_embeddings = get_embeddings(conn)
            archived_embeddings = get_embeddings(conn, archived_only=True)

            self.assertEqual([item["id"] for item in active_embeddings], [note1_id])
            self.assertEqual([item["id"] for item in archived_embeddings], [note2_id])
            conn.close()


if __name__ == "__main__":
    unittest.main()
