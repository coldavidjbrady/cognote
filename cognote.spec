# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path.cwd().resolve()
FRONTEND_DIST = ROOT / "frontend" / "dist"
EXPORTER_SCRIPT = ROOT / "apple_notes_exporter_v4.py"

datas = []
if FRONTEND_DIST.exists():
    datas.append((str(FRONTEND_DIST), "frontend/dist"))
if EXPORTER_SCRIPT.exists():
    datas.append((str(EXPORTER_SCRIPT), "resources"))

hiddenimports = [
    *collect_submodules("uvicorn"),
    *collect_submodules("uvicorn.loops"),
    *collect_submodules("uvicorn.protocols"),
    *collect_submodules("uvicorn.lifespan"),
    *collect_submodules("fastapi"),
    *collect_submodules("openai"),
    *collect_submodules("openpyxl"),
    "backend.app.main",
    "backend.app.desktop",
]

block_cipher = None

a = Analysis(
    ["scripts/cognote_desktop_entry.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Cognote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Cognote",
)

app = BUNDLE(
    coll,
    name="Cognote.app",
    icon=None,
    bundle_identifier="com.coldavidjbrady.cognote",
)
