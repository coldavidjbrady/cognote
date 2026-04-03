# Apple Notes Exporter for macOS

This script bulk-exports Apple Notes into one merged output set.

## What it creates

- `notes_export.xlsx` — one workbook with all notes in a single sheet plus a summary tab
- `notes_export.csv`
- `notes_export.jsonl`
- `notes_merged.md`

## Requirements

- macOS
- Apple Notes app
- Python 3
- `openpyxl` only if you want `.xlsx` output

## Recommended clean setup

```bash
mkdir -p ~/apple-notes-export
cd ~/apple-notes-export
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install openpyxl
```

Copy `apple_notes_exporter.py` into that folder, then run:

```bash
python apple_notes_exporter.py --output-dir ~/Desktop/notes-export
```

## Optional examples

Export only one account:

```bash
python apple_notes_exporter.py --output-dir ~/Desktop/notes-export --account "iCloud"
```

Skip Excel generation:

```bash
python apple_notes_exporter.py --output-dir ~/Desktop/notes-export --skip-xlsx
```

## macOS permissions

The first run will usually trigger a prompt asking you to allow your terminal app to control **Notes**. Approve it or the export will fail.

If you denied it earlier, go to:

- System Settings
- Privacy & Security
- Automation

Then allow your terminal app to control **Notes**.

## Notes and limitations

- This version focuses on text and metadata.
- Rich attachments are not extracted as separate files.
- HTML from Notes is preserved in the CSV/JSONL/XLSX as `body_html`, and a simplified text version is written as `body_text`.
- The script must run on your Mac because it uses AppleScript to talk to the local Notes app.

## Troubleshooting

If you get an error from `osascript`, verify:

```bash
python3 --version
osascript -e 'tell application "Notes" to count of notes'
```

If the second command errors, it is usually an Automation permission problem.
