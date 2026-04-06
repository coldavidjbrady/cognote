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


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.db import connect, init_db, list_notes


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


class PackagedFlowTests(unittest.TestCase):
    def tearDown(self) -> None:
        config = importlib.import_module("backend.app.config")
        config.clear_settings_cache()
        if hasattr(sys, "_MEIPASS"):
            delattr(sys, "_MEIPASS")
        if hasattr(sys, "frozen"):
            delattr(sys, "frozen")

    def test_packaged_mode_prefers_bundled_exporter_resource(self) -> None:
        config = importlib.import_module("backend.app.config")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            bundled_resources = temp_root / "bundle" / "resources"
            bundled_resources.mkdir(parents=True, exist_ok=True)
            bundled_exporter = bundled_resources / "apple_notes_exporter_v4.py"
            bundled_exporter.write_text("# bundled exporter\n", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
            ):
                with patch("backend.app.config.get_openai_api_key", return_value=None):
                    setattr(sys, "_MEIPASS", str(temp_root / "bundle"))
                    config.clear_settings_cache()
                    settings = config.get_settings()

        self.assertEqual(settings.runtime_mode, "packaged")
        self.assertEqual(settings.exporter_script_path, bundled_exporter.resolve())

    def test_packaged_setup_job_writes_artifacts_and_creates_db(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exporter_script = temp_root / "apple_notes_exporter_v4.py"
            exporter_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
            ):
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)

                def fake_subprocess_run(command, capture_output, text, check, cwd):
                    output_dir = Path(command[command.index("--output-dir") + 1])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / "notes_export.csv").write_text("id,title\nnote-1,Recipe\n", encoding="utf-8")
                    (output_dir / "notes_export.jsonl").write_text(
                        "\n".join(
                            [
                                note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                                note_jsonl_line("note-2", "Travel", "paris packing list"),
                            ]
                        ),
                        encoding="utf-8",
                    )
                    (output_dir / "notes_merged.md").write_text("# Export\n", encoding="utf-8")
                    (output_dir / "export_summary.json").write_text(
                        '{"total_notes": 2, "total_folders": 1}',
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(command, 0, stdout="export ok\n", stderr="")

                with patch.object(jobs.subprocess, "run", side_effect=fake_subprocess_run):
                    status = manager.start_setup(
                        schemas.SyncRunRequest(skip_xlsx=True, skip_embeddings=True),
                        run_async=False,
                    )

                self.assertEqual(status["status"], "complete")
                self.assertEqual(status["runtime_mode"], "packaged")
                self.assertTrue(Path(settings.db_path).exists())
                self.assertEqual(Path(status["output_dir"]).resolve().parent, settings.exports_root_dir.resolve())
                self.assertTrue(status["artifacts"]["jsonl_exists"])
                self.assertTrue(status["artifacts"]["csv_exists"])
                self.assertTrue(status["artifacts"]["markdown_exists"])
                self.assertTrue(status["artifacts"]["summary_exists"])
                self.assertFalse(status["artifacts"]["xlsx_exists"])
                self.assertEqual(status["warnings"], [])

                conn = connect(settings.db_path)
                init_db(conn)
                active_notes = list_notes(conn)
                conn.close()

        self.assertEqual(sorted(item["title"] for item in active_notes), ["Recipe", "Travel"])

    def test_packaged_sync_archives_missing_notes_and_creates_new_snapshot(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exporter_script = temp_root / "apple_notes_exporter_v4.py"
            exporter_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
            ):
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)
                export_payloads = [
                    [
                        note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                        note_jsonl_line("note-2", "Travel", "paris packing list"),
                    ],
                    [
                        note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                    ],
                ]

                def fake_subprocess_run(command, capture_output, text, check, cwd):
                    output_dir = Path(command[command.index("--output-dir") + 1])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    payload_lines = export_payloads.pop(0)
                    (output_dir / "notes_export.csv").write_text("id,title\n", encoding="utf-8")
                    (output_dir / "notes_export.jsonl").write_text(
                        "\n".join(payload_lines),
                        encoding="utf-8",
                    )
                    (output_dir / "notes_merged.md").write_text("# Export\n", encoding="utf-8")
                    (output_dir / "export_summary.json").write_text(
                        '{"total_notes": %d}' % len(payload_lines),
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(command, 0, stdout="export ok\n", stderr="")

                with patch.object(jobs.subprocess, "run", side_effect=fake_subprocess_run):
                    first_status = manager.start_setup(
                        schemas.SyncRunRequest(skip_xlsx=True, skip_embeddings=True),
                        run_async=False,
                    )
                    second_status = manager.start_sync(
                        schemas.SyncRunRequest(skip_xlsx=True, skip_embeddings=True),
                        run_async=False,
                    )

                self.assertEqual(first_status["status"], "complete")
                self.assertEqual(second_status["status"], "complete")
                self.assertNotEqual(first_status["output_dir"], second_status["output_dir"])
                self.assertEqual(second_status["import_summary"]["archived"], 1)

                conn = connect(settings.db_path)
                init_db(conn)
                active_notes = list_notes(conn)
                archived_notes = list_notes(conn, archived_only=True)
                conn.close()

        self.assertEqual([item["title"] for item in active_notes], ["Recipe"])
        self.assertEqual([item["title"] for item in archived_notes], ["Travel"])

    def test_packaged_job_fails_when_exporter_script_is_missing(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            missing_exporter = temp_root / "does-not-exist.py"

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(missing_exporter),
            ):
                config.clear_settings_cache()
                manager = jobs.SyncJobManager(config.get_settings())
                status = manager.start_setup(schemas.SyncRunRequest(skip_xlsx=True), run_async=False)

                self.assertEqual(status["status"], "failed")
                self.assertIn(str(missing_exporter), status["error"])
                self.assertIsNotNone(status["log_path"])
                failure_log = Path(status["log_path"])
                self.assertTrue(failure_log.exists())
                failure_text = failure_log.read_text(encoding="utf-8")
                self.assertIn("Exporter script not found", failure_text)
                self.assertIn(str(missing_exporter), failure_text)
                self.assertIn("traceback:", failure_text)


    def test_packaged_job_warns_when_optional_artifacts_are_missing(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exporter_script = temp_root / "apple_notes_exporter_v4.py"
            exporter_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
            ):
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)

                def fake_subprocess_run(command, capture_output, text, check, cwd):
                    output_dir = Path(command[command.index("--output-dir") + 1])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / "notes_export.csv").write_text("id,title\n", encoding="utf-8")
                    (output_dir / "notes_export.jsonl").write_text(
                        note_jsonl_line("note-1", "Recipe", "banana bread recipe"),
                        encoding="utf-8",
                    )
                    (output_dir / "notes_merged.md").write_text("# Export\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, stdout="export ok\n", stderr="")

                with patch.object(jobs.subprocess, "run", side_effect=fake_subprocess_run):
                    status = manager.start_setup(
                        schemas.SyncRunRequest(skip_xlsx=False, skip_embeddings=True),
                        run_async=False,
                    )

        self.assertEqual(status["status"], "complete")
        self.assertFalse(status["artifacts"]["summary_exists"])
        self.assertFalse(status["artifacts"]["xlsx_exists"])
        self.assertGreaterEqual(len(status["warnings"]), 2)
        self.assertTrue(any("export_summary.json" in warning for warning in status["warnings"]))
        self.assertTrue(any("XLSX export" in warning for warning in status["warnings"]))

    def test_packaged_job_fails_when_jsonl_is_missing(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exporter_script = temp_root / "apple_notes_exporter_v4.py"
            exporter_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
            ):
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)

                def fake_subprocess_run(command, capture_output, text, check, cwd):
                    output_dir = Path(command[command.index("--output-dir") + 1])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / "notes_export.csv").write_text("id,title\n", encoding="utf-8")
                    (output_dir / "notes_merged.md").write_text("# Export\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, stdout="export ok\n", stderr="")

                with patch.object(jobs.subprocess, "run", side_effect=fake_subprocess_run):
                    status = manager.start_setup(
                        schemas.SyncRunRequest(skip_xlsx=True, skip_embeddings=True),
                        run_async=False,
                    )

        self.assertEqual(status["status"], "failed")
        self.assertIn("notes_export.jsonl", status["error"])

    def test_packaged_job_skips_invalid_notes_and_writes_import_error_log(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")
        db = importlib.import_module("backend.app.db")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exporter_script = temp_root / "apple_notes_exporter_v4.py"
            exporter_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
            ):
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)

                def fake_subprocess_run(command, capture_output, text, check, cwd):
                    output_dir = Path(command[command.index("--output-dir") + 1])
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / "notes_export.csv").write_text("id,title\n", encoding="utf-8")
                    (output_dir / "notes_export.jsonl").write_text(
                        "\n".join(
                            [
                                '{"id": "note-1", "title": "Broken"',
                                note_jsonl_line("note-2", "Recipe", "banana bread recipe"),
                            ]
                        ),
                        encoding="utf-8",
                    )
                    (output_dir / "notes_merged.md").write_text("# Export\n", encoding="utf-8")
                    (output_dir / "export_summary.json").write_text(
                        '{"total_notes": 2}',
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(command, 0, stdout="export ok\n", stderr="")

                with patch.object(jobs.subprocess, "run", side_effect=fake_subprocess_run):
                    status = manager.start_setup(
                        schemas.SyncRunRequest(skip_xlsx=True, skip_embeddings=True),
                        run_async=False,
                    )

                self.assertEqual(status["status"], "complete")
                self.assertEqual(status["import_summary"]["imported"], 1)
                self.assertEqual(status["import_summary"]["failed"], 1)
                self.assertIsNone(status["error"])
                self.assertIsNotNone(status["import_error_log_path"])
                error_log = Path(status["import_error_log_path"])
                self.assertTrue(error_log.exists())
                error_text = error_log.read_text(encoding="utf-8")
                self.assertIn("Invalid JSONL on line 1", error_text)

                conn = db.connect(settings.db_path)
                db.init_db(conn)
                active_notes = db.list_notes(conn)
                conn.close()

                self.assertEqual([item["title"] for item in active_notes], ["Recipe"])

    def test_frozen_packaged_mode_runs_exporter_in_process(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exporter_script = temp_root / "packaged_exporter.py"
            exporter_script.write_text(
                """
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--progress-every")
    parser.add_argument("--account", default=None)
    parser.add_argument("--skip-xlsx", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = "banana bread recipe"
    payload = {
        "id": "note-1",
        "account": "iCloud",
        "folder": "Inbox",
        "title": "Recipe",
        "created": "2024-01-01 10:00:00",
        "modified": "2024-01-02 10:00:00",
        "body_text": body,
        "body_html": f"<p>{body}</p>",
        "word_count": 3,
        "char_count": 20,
    }
    (out_dir / "notes_export.csv").write_text("id,title\\nnote-1,Recipe\\n", encoding="utf-8")
    (out_dir / "notes_export.jsonl").write_text(json.dumps(payload), encoding="utf-8")
    (out_dir / "notes_merged.md").write_text("# Export\\n", encoding="utf-8")
    (out_dir / "export_summary.json").write_text(json.dumps({"total_notes": 1}), encoding="utf-8")
    print("packaged exporter wrote snapshot")
    return 0
                """.strip(),
                encoding="utf-8",
            )

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
            ):
                setattr(sys, "frozen", True)
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)

                with patch.object(jobs.subprocess, "run", side_effect=AssertionError("subprocess should not run")):
                    status = manager.start_setup(
                        schemas.SyncRunRequest(skip_xlsx=True, skip_embeddings=True),
                        run_async=False,
                    )

        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["runtime_mode"], "packaged")
        self.assertIn("packaged_exporter.py", " ".join(status["exporter_command"]))
        self.assertIn("packaged exporter wrote snapshot", status["export_summary"]["stdout_excerpt"])

    def test_frozen_packaged_mode_supports_exporter_modules_with_dataclasses(self) -> None:
        config = importlib.import_module("backend.app.config")
        jobs = importlib.import_module("backend.app.jobs")
        schemas = importlib.import_module("backend.app.schemas")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exporter_script = temp_root / "packaged_exporter_with_dataclass.py"
            exporter_script.write_text(
                """
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ExportRow:
    id: str
    account: str
    folder: str
    title: str
    created: str
    modified: str
    body_text: str
    body_html: str
    word_count: int
    char_count: int


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--progress-every")
    parser.add_argument("--account", default=None)
    parser.add_argument("--skip-xlsx", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    row = ExportRow(
        id="note-1",
        account="iCloud",
        folder="Inbox",
        title="Recipe",
        created="2024-01-01 10:00:00",
        modified="2024-01-02 10:00:00",
        body_text="banana bread recipe",
        body_html="<p>banana bread recipe</p>",
        word_count=3,
        char_count=20,
    )
    (out_dir / "notes_export.csv").write_text("id,title\\nnote-1,Recipe\\n", encoding="utf-8")
    (out_dir / "notes_export.jsonl").write_text(json.dumps(asdict(row)), encoding="utf-8")
    (out_dir / "notes_merged.md").write_text("# Export\\n", encoding="utf-8")
    (out_dir / "export_summary.json").write_text(json.dumps({"total_notes": 1}), encoding="utf-8")
    return 0
                """.strip(),
                encoding="utf-8",
            )

            with temporary_env(
                COGNOTE_RUNTIME_MODE="packaged",
                COGNOTE_APP_SUPPORT_DIR=str(temp_root / "app-support"),
                COGNOTE_EXPORTER_SCRIPT_PATH=str(exporter_script),
            ):
                setattr(sys, "frozen", True)
                config.clear_settings_cache()
                settings = config.get_settings()
                manager = jobs.SyncJobManager(settings)

                with patch.object(jobs.subprocess, "run", side_effect=AssertionError("subprocess should not run")):
                    status = manager.start_setup(
                        schemas.SyncRunRequest(skip_xlsx=True, skip_embeddings=True),
                        run_async=False,
                    )

        self.assertEqual(status["status"], "complete")
        self.assertTrue(status["artifacts"]["jsonl_exists"])


if __name__ == "__main__":
    unittest.main()
