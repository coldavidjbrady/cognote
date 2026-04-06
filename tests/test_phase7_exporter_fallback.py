from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ExporterFallbackTests(unittest.TestCase):
    def test_bulk_fallback_recovers_notes_when_streaming_returns_zero(self) -> None:
        exporter = importlib.import_module("apple_notes_exporter_v4")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "export"
            fallback_note = exporter.NoteRecord(
                account="iCloud",
                folder="Inbox",
                id="note-1",
                title="Recovered",
                created="2024-01-01 10:00:00",
                modified="2024-01-02 10:00:00",
                body_html="<p>Recovered body</p>",
                body_text="Recovered body",
                word_count=2,
                char_count=14,
            )

            with patch.object(exporter.sys, "platform", "darwin"):
                with patch.object(exporter, "fetch_folders", return_value=[("iCloud", "Inbox")]):
                    with patch.object(exporter, "fetch_folder_notes", return_value=iter(())):
                        with patch.object(exporter, "fetch_all_notes", return_value=[fallback_note]):
                            exit_code = exporter.main(
                                [
                                    "--output-dir",
                                    str(output_dir),
                                    "--skip-xlsx",
                                ]
                            )

            self.assertEqual(exit_code, 0)

            summary = json.loads((output_dir / "export_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["total_notes"], 1)
            self.assertEqual(summary["total_folders"], 1)

            jsonl_lines = (output_dir / "notes_export.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(jsonl_lines), 1)
            payload = json.loads(jsonl_lines[0])
            self.assertEqual(payload["title"], "Recovered")

    def test_write_xlsx_records_sanitizes_illegal_control_characters(self) -> None:
        exporter = importlib.import_module("apple_notes_exporter_v4")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "notes_export.xlsx"
            note = exporter.NoteRecord(
                account="On My Mac",
                folder="Notes",
                id="note-1",
                title="Mercola-Red light Therapy",
                created="2024-01-01 10:00:00",
                modified="2024-01-02 10:00:00",
                body_html="<p>The Bene\x00ts of Red Light Therapy</p>",
                body_text="The Bene\x00ts of Red Light Therapy",
                word_count=7,
                char_count=34,
            )

            wrote_xlsx = exporter.write_xlsx_records([note], output_path)

            self.assertTrue(wrote_xlsx)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
