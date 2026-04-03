# Apple Notes Exporter v4

A more reliable bulk exporter for Apple Notes on macOS.

This version is designed to work better with larger note libraries by exporting **folder by folder** instead of trying to build one massive payload in a single AppleScript call.

## What v4 does

The exporter pulls note content and metadata from Apple Notes through macOS automation, then writes the results into merged output files you can search, analyze, or import elsewhere.

### Output files
- `notes_export.csv` — one row per note
- `notes_export.jsonl` — one JSON object per note
- `notes_merged.md` — all notes merged into one Markdown file
- `notes_export.xlsx` — optional Excel workbook
- `export_summary.json` — summary stats from the export
- `.export_state.json` — checkpoint file used for resume mode

## How the v4 process works

### 1) Discover folders first
The script starts by asking Apple Notes for the folder structure across your accounts.

It builds a list like:

- `iCloud / Notes`
- `iCloud / Work / Projects`
- `On My Mac / Archive`

This is important because v4 exports **one folder at a time** instead of asking Notes for everything at once.

### 2) Resolve each folder path safely
For each folder path, the script re-resolves the account and folder directly inside AppleScript before reading notes.

That is the key reliability improvement in v4.

Earlier versions passed account references around more directly, which can cause AppleScript / Notes to throw weird coercion errors like:

- `Can't make |folders| of account id ... into type specifier (-1700)`

v4 avoids that by looking up the account fresh inside the folder-resolution handler.

### 3) Export notes from one folder at a time
For each folder, the script fetches:
- account
- folder
- note id
- title
- creation date
- modification date
- body HTML

Then Python converts the HTML-ish body into plain text for easier downstream use.

### 4) Write output incrementally
Instead of holding the full export in memory, v4 writes notes as they are processed.

That means:
- CSV grows row by row
- JSONL grows object by object
- Markdown grows note by note
- XLSX is written in streaming mode when `openpyxl` is installed

This is much safer for larger note libraries.

### 5) Save progress with resume mode
If you run with `--resume`, the script writes a checkpoint file after each completed folder.

If the run fails halfway through, rerun the same command and it will skip folders that already completed.

That saves you from re-exporting everything because AppleScript decided to become performance art.

## Why v4 is better than the earlier versions

### Earlier versions
The earlier scripts tried to:
- ask Notes for everything at once
- build one giant JSON payload in AppleScript
- parse that whole payload in Python

That can work for small libraries, but it gets fragile as note count and note size grow.

### v4
v4 improves that by:
- processing **folder by folder**
- avoiding one giant in-memory JSON blob
- writing files incrementally
- supporting checkpoint/resume
- using a more reliable folder-resolution approach in AppleScript

## Requirements

### macOS
This script must run on **macOS** because it uses `osascript` to automate the Notes app.

### Automation permission
The app running the script must be allowed to control Notes.

On first run, macOS may prompt you to allow:
- Terminal
- iTerm
- VS Code
- Python

Approve that request.

If you deny it, the script will fail.

### Python
Use a virtual environment if you want to keep your main Python installation clean.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install openpyxl
```

`openpyxl` is only needed if you want the Excel output.

## Basic usage

```bash
python apple_notes_exporter_v4.py --output-dir ~/Desktop/notes-export
```

## Recommended usage for large exports

```bash
python apple_notes_exporter_v4.py --output-dir ~/Desktop/notes-export --resume
```

## Useful options

### Resume after interruption
```bash
python apple_notes_exporter_v4.py --output-dir ~/Desktop/notes-export --resume
```

### Export a single account
```bash
python apple_notes_exporter_v4.py --output-dir ~/Desktop/notes-export --account "iCloud" --resume
```

### Skip Excel generation
```bash
python apple_notes_exporter_v4.py --output-dir ~/Desktop/notes-export --skip-xlsx --resume
```

### Reduce progress message frequency
```bash
python apple_notes_exporter_v4.py --output-dir ~/Desktop/notes-export --resume --progress-every 100
```

## Resume file behavior

When `--resume` is enabled, the script writes a state file:

- `.export_state.json`

This file tracks:
- which folders already completed
- note counts
- word counts
- account and folder totals

If the export is interrupted, rerunning the same command uses that file to continue.

If you want to start fresh, delete the output folder contents or use a new output directory.

## Output details

### CSV
Best for:
- Excel import
- filtering
- quick backups
- lightweight analysis

### JSONL
Best for:
- scripting
- data pipelines
- loading into other tools
- per-note processing

### Markdown
Best for:
- readable archive
- search in editors
- quick manual review

### XLSX
Best for:
- direct use in Excel
- sorting and filtering
- handing to non-technical humans who prefer grids over joy

## Known limitations

v4 focuses on **note text and metadata**.

It does **not** currently:
- extract attachments into separate files
- preserve rich formatting perfectly
- export embedded images as standalone assets
- handle every Apple Notes oddity ever invented

Also, performance still depends on Apple Notes automation speed. The script is more scalable now, but Notes is still the slowest part of the stack.

## Troubleshooting

### Error: Automation / osascript failed
Make sure:
- you are on macOS
- Terminal/iTerm/VS Code/Python has permission to control Notes
- Notes is available and working normally

### Error: no folders found
Check that:
- the selected account name is correct
- Notes actually contains folders/notes in that account
- the Notes app has fully synced

### Export interrupted midway
Rerun with:

```bash
python apple_notes_exporter_v4.py --output-dir ~/Desktop/notes-export --resume
```

## Practical scaling guidance

### Likely fine
- hundreds of notes
- low thousands of notes

### Maybe slow but still workable
- several thousand notes
- many large notes

### Still not magical
- extremely large libraries
- attachment-heavy libraries
- weirdly nested Notes setups that AppleScript decides to hate that day

## Suggested next improvements

If you want a v5 later, the next useful upgrades would be:
- attachment extraction
- deduplication
- incremental exports based on modification date
- better HTML-to-text cleanup
- separate per-folder exports
- a simple Mac app wrapper

## Summary

v4 is the first version in this line I would call reasonably trustworthy for a real export.

It works by:
1. listing folders
2. resolving one folder at a time
3. exporting notes from that folder
4. writing files incrementally
5. saving checkpoints for resume mode

That is a lot less elegant than “one giant magic export,” but a lot more likely to survive contact with Apple Notes.
