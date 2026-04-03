# Apple Notes Export + Search App

This repo now contains two connected pieces:

- `apple_notes_exporter_v4.py` exports Apple Notes into structured files on macOS
- a new local web app lets you search those notes with keyword, semantic, or hybrid retrieval

The app is designed to stay local-first:

- notes live in `SQLite`
- keyword search uses `SQLite FTS5`
- semantic search uses OpenAI embeddings when `OPENAI_API_KEY` is available
- the UI is a React app with a reader-style note view and manual collections/associations

## Architecture

### Backend
- `backend/app/main.py` exposes the FastAPI API
- `backend/app/db.py` owns the SQLite schema and note/collection/link queries
- `backend/app/search.py` combines FTS keyword search with embedding similarity
- `backend/app/embeddings.py` wraps OpenAI embedding calls

### Frontend
- `frontend/` is a Vite + React app
- left rail: library summary and collections
- center column: search results
- right column: full note reader, manual associations, and suggested related notes

### Import pipeline
- `scripts/import_notes.py` loads `notes_export.jsonl` into SQLite
- if `OPENAI_API_KEY` is set, the same import step also generates embeddings for changed notes

## Recommended note attributes

The UI currently emphasizes:

- title
- folder path
- modified date
- note body
- related notes
- collections

It keeps lower-signal or technical fields out of the primary reading view:

- raw Apple Notes id
- raw HTML
- export bookkeeping fields

Those can still stay in the database for future admin/debug views.

## Setup

### 1) Python environment

From the repo root:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

You only need to reinstall when dependencies change or `.venv` is recreated.

### 2) Frontend dependencies

```bash
cd frontend
npm install
```

### 3) Environment variables

Create a `.env` file in the repo root with:

```bash
OPENAI_API_KEY=your_key_here
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
NOTES_DB_PATH=/Users/davidjbrady/apple-notes-export/data/notes.db
VITE_API_BASE_URL=http://127.0.0.1:8000
SEMANTIC_MIN_SCORE=0.64
```

`OPENAI_API_KEY` is optional if you only want keyword search.

`SEMANTIC_MIN_SCORE` controls semantic strictness (`0.0` to `1.0`):
- lower values: broader recall, more potential noise
- higher values: stricter relevance, fewer results

## Import notes into SQLite

Run this after you have `notes_export.jsonl` from the exporter:

```bash
./.venv/bin/python scripts/import_notes.py --jsonl /absolute/path/to/notes_export.jsonl
```

If you want to skip embeddings during import:

```bash
./.venv/bin/python scripts/import_notes.py --jsonl /absolute/path/to/notes_export.jsonl --skip-embeddings
```

If you enabled `OPENAI_API_KEY` after an earlier import, run a one-time embedding backfill:

```bash
set -a && source .env && set +a && ./.venv/bin/python - <<'PY'
from pathlib import Path
from backend.app.config import get_settings
from backend.app.db import connect, init_db
from scripts.import_notes import embed_pending_notes

settings = get_settings()
db_path = Path(settings.db_path)
conn = connect(db_path)
init_db(conn)
conn.execute("""
UPDATE notes
SET embedding_status = 'pending', embedding_updated_at = NULL
WHERE id NOT IN (SELECT note_id FROM note_embeddings)
""")
conn.commit()
conn.close()
embed_pending_notes(db_path, batch_size=50)
PY
```

## Run the app

### Backend

```bash
set -a && source .env && set +a && ./.venv/bin/uvicorn backend.app.main:app --reload
```

The API will start on `http://127.0.0.1:8000`.

### Frontend

In another terminal:

```bash
cd frontend
npm run dev
```

The UI will start on `http://127.0.0.1:5173`.

## Search behavior notes

- keyword mode uses SQLite FTS5 and works best with focused terms (for example: `wifi`)
- natural-language queries are normalized before keyword matching
- semantic and hybrid modes use OpenAI embeddings when `OPENAI_API_KEY` is set
- result filtering uses `SEMANTIC_MIN_SCORE` to avoid low-relevance semantic tail results

## Current MVP features

- hybrid search: exact terms plus semantic similarity
- recent-notes fallback when no query is entered
- full note reading view
- manual collections like `Health`, `Recipes`, or `Research`
- manual note-to-note associations
- automatic related-note suggestions from embeddings

## Good next improvements

- normalize and preserve more rich note formatting
- attachment extraction and preview support
- filters by folder/account/date range
- saved searches
- tag extraction and lightweight AI summaries
