from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


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


class SyncJobManagerTests(unittest.TestCase):
    def tearDown(self) -> None:
        config = importlib.import_module("backend.app.config")
        config.clear_settings_cache()

    def test_sync_job_runs_pipeline_and_records_complete_status(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exports_root = temp_root / "exports"
            db_path = temp_root / "notes.db"
            exporter_script = temp_root / "apple_notes_exporter_v4.py"
            exporter_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                COGNOTE_EXPORTS_ROOT_DIR=str(exports_root),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
                NOTES_DB_PATH=str(db_path),
            ):
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)

                def fake_subprocess_run(command, capture_output, text, check, cwd):
                    output_dir = Path(command[command.index("--output-dir") + 1])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / "notes_export.csv").write_text("id,title\nnote-1,Test\n", encoding="utf-8")
                    (output_dir / "notes_export.jsonl").write_text('{"id":"note-1"}\n', encoding="utf-8")
                    (output_dir / "notes_merged.md").write_text("# Test\n", encoding="utf-8")
                    (output_dir / "export_summary.json").write_text(
                        '{"total_notes": 1, "output_dir": "%s"}' % output_dir,
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="Export complete\nJSONL: notes_export.jsonl\nSUMMARY: export_summary.json\n",
                        stderr="",
                    )

                with patch.object(jobs.subprocess, "run", side_effect=fake_subprocess_run):
                    with patch.object(jobs, "import_notes_file", return_value=(12, 3, 2)):
                        with patch.object(jobs, "embed_pending_notes", return_value=5):
                            status = manager.start_sync(
                                schemas.SyncRunRequest(skip_xlsx=True),
                                run_async=False,
                            )

                self.assertEqual(status["status"], "complete")
                self.assertEqual(status["job_type"], "sync")
                self.assertEqual(status["phase"], "complete")
                self.assertEqual(status["import_summary"]["imported"], 12)
                self.assertEqual(status["import_summary"]["changed"], 3)
                self.assertEqual(status["import_summary"]["archived"], 2)
                self.assertEqual(status["import_summary"]["embedded"], 5)
                self.assertEqual(Path(status["output_dir"]).resolve().parent, exports_root.resolve())
                self.assertIn("stdout_excerpt", status["export_summary"])
                self.assertTrue(Path(status["artifacts"]["jsonl_path"]).exists())

    def test_manager_prevents_overlapping_jobs(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                NOTES_DB_PATH=str(Path(temp_dir) / "notes.db"),
            ):
                config.clear_settings_cache()
                manager = jobs.SyncJobManager(config.get_settings())
                manager._status = {
                    "status": "running",
                    "job_id": "job-1",
                    "job_type": "sync",
                    "phase": "exporting_notes",
                    "message": "Running",
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "finished_at": None,
                    "error": None,
                    "output_dir": None,
                    "artifacts": None,
                    "export_summary": None,
                    "import_summary": None,
                }

                with self.assertRaises(RuntimeError):
                    manager.start_setup(schemas.SyncRunRequest(), run_async=False)


class JobEndpointTests(unittest.TestCase):
    def _load_main_module(self):
        module = importlib.import_module("backend.app.main")
        return importlib.reload(module)

    def test_jobs_status_endpoint_returns_manager_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                NOTES_DB_PATH=str(Path(temp_dir) / "notes.db"),
            ):
                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                fake_status = {
                    "status": "complete",
                    "job_id": "job-123",
                    "job_type": "sync",
                    "phase": "complete",
                    "message": "Done",
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "finished_at": "2024-01-01T00:05:00+00:00",
                    "error": None,
                    "output_dir": "/tmp/out",
                    "artifacts": {},
                    "export_summary": {},
                    "import_summary": {"imported": 1, "changed": 1, "archived": 0, "embedded": 0},
                }

                with patch.object(main.sync_job_manager, "get_status", return_value=fake_status):
                    with TestClient(main.app) as client:
                        response = client.get("/api/jobs/status")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["job_id"], "job-123")
                self.assertIn("openai_enabled", response.json())

    def test_setup_endpoint_returns_conflict_when_job_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with temporary_env(
                COGNOTE_RUNTIME_MODE="dev",
                NOTES_DB_PATH=str(Path(temp_dir) / "notes.db"),
            ):
                config = importlib.import_module("backend.app.config")
                config.clear_settings_cache()
                main = self._load_main_module()

                with patch.object(main.sync_job_manager, "start_setup", side_effect=RuntimeError("busy")):
                    with TestClient(main.app) as client:
                        response = client.post("/api/jobs/setup", json={})

                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"], "busy")


if __name__ == "__main__":
    unittest.main()
