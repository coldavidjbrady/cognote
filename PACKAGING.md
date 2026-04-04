# Packaging Cognote For macOS

This guide is for rebuilding the packaged desktop app from source.

## Packaging stack

Cognote is packaged as:

- FastAPI backend
- built React frontend
- native macOS app shell via `pywebview`
- `.app` bundle generated with `PyInstaller`

The packaged app starts a localhost service internally and stores runtime data under:

- `~/Library/Application Support/Cognote`

## One-time setup

From the repo root:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-packaging.txt
cd frontend
npm install
cd ..
```

## Build the app

Run:

```bash
./scripts/build_mac_app.sh
```

That script will:

- build the frontend with Vite
- run `PyInstaller`
- output the app bundle at:

```bash
dist/Cognote.app
```

## Included packaged resources

The bundle includes:

- the desktop entrypoint
- backend application code
- built frontend assets from `frontend/dist`
- `apple_notes_exporter_v4.py`

The packaged runtime expects:

- frontend assets under bundled `frontend/dist`
- exporter script under bundled `resources/`

The current packaging config handles that layout already.

## Main packaging files

- [cognote.spec](/Users/davidjbrady/Cognote/cognote.spec)
- [scripts/build_mac_app.sh](/Users/davidjbrady/Cognote/scripts/build_mac_app.sh)
- [scripts/cognote_desktop_entry.py](/Users/davidjbrady/Cognote/scripts/cognote_desktop_entry.py)
- [requirements-packaging.txt](/Users/davidjbrady/Cognote/requirements-packaging.txt)

## Validate the built app

Recommended validation flow:

1. Launch `dist/Cognote.app`.
2. Confirm the window opens.
3. Confirm first-run setup appears on a clean machine or clean user profile.
4. Confirm setup can import notes and create the local DB.
5. Relaunch the app and verify it reuses the existing DB.
6. Run `Sync notes` and verify refresh behavior.

## Developer workflow safety

Packaging is additive. These dev commands should still work after packaging changes:

```bash
set -a && source .env && set +a && ./.venv/bin/uvicorn backend.app.main:app --reload
```

```bash
cd frontend
npm run dev
```

If you change the frontend and want the packaged app to reflect it, rebuild:

```bash
cd frontend
npm run build
cd ..
./scripts/build_mac_app.sh
```

## Notes

- `PyInstaller` cache is redirected into repo-local `.pyinstaller/`
- top-level `build/` and `dist/` outputs are gitignored
- the current bundle is built and launches locally, but signing and notarization are still separate future work if you want smoother distribution
