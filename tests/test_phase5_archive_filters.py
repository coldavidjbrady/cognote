from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.importer import import_notes_lines


@contextmanager
def temporary_env(**updates: str | None):
    previous = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def note_jsonl_line(source_id: str, title: str, body_text: str) -> str:
    return (
        '{"id":"%s","account":"iCloud","folder":"Inbox","title":"%s",'
        '"created":"2024-01-01 10:00:00","modified":"2024-01-02 10:00:00",'
        '"body_text":"%s","body_html":"<p>%s</p>","word_count":3,"char_count":20}'
        % (source_id, title, body_text, body_text)
    )


class ArchiveFilterEndpointTests(unittest.TestCase):
    def _load_main_module(self):
        module = importlib.import_module("backend.app.main")
        return importlib.reload(module)

    def tearDown(self) -> None:
        config = importlib.import_module("backend.app.config")
        config.clear_settings_cache()

    def test_notes_endpoint_supports_archived_only_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "notes.db"
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                NOTES_DB_PATH=str(db_path),
            ):
                import_notes_lines(
                    [
                        note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                        note_jsonl_line("note-2", "Travel", "paris packing list"),
                    ],
                    db_path,
                )
                import_notes_lines(
                    [
                        note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                    ],
                    db_path,
                )

                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                with TestClient(main.app) as client:
                    active_response = client.get("/api/notes")
                    archived_response = client.get("/api/notes?archived_only=true")

        self.assertEqual(active_response.status_code, 200)
        self.assertEqual([item["title"] for item in active_response.json()["results"]], ["Recipe"])
        self.assertEqual(archived_response.status_code, 200)
        self.assertEqual([item["title"] for item in archived_response.json()["results"]], ["Travel"])
        self.assertEqual(int(archived_response.json()["results"][0]["is_archived"]), 1)

    def test_search_endpoint_supports_archived_only_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "notes.db"
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                NOTES_DB_PATH=str(db_path),
            ):
                import_notes_lines(
                    [
                        note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                        note_jsonl_line("note-2", "Travel", "paris packing list"),
                    ],
                    db_path,
                )
                import_notes_lines(
                    [
                        note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                    ],
                    db_path,
                )

                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                with TestClient(main.app) as client:
                    active_response = client.get("/api/search?q=paris&mode=keyword")
                    archived_response = client.get("/api/search?q=paris&mode=keyword&archived_only=true")

        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(active_response.json()["results"], [])
        self.assertEqual(archived_response.status_code, 200)
        self.assertEqual([item["title"] for item in archived_response.json()["results"]], ["Travel"])
        self.assertEqual(int(archived_response.json()["results"][0]["is_archived"]), 1)


if __name__ == "__main__":
    unittest.main()
