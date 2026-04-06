from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from .secrets import get_openai_api_key


BASE_DIR = Path(__file__).resolve().parents[2]
APP_NAME = "Cognote"
RuntimeMode = Literal["dev", "packaged"]
OpenAIKeySource = Literal["env", "keychain", "none"]
DEFAULT_DB_PATH = BASE_DIR / "data" / "notes.db"
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_CORS_ORIGINS)
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _runtime_mode() -> RuntimeMode:
    raw = (os.getenv("COGNOTE_RUNTIME_MODE") or "").strip().lower()
    if raw == "packaged":
        return "packaged"
    if raw == "dev":
        return "dev"
    if getattr(sys, "frozen", False):
        return "packaged"
    return "dev"


def _resource_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root).resolve()
    return BASE_DIR


def _default_app_support_dir() -> Path:
    override = os.getenv("COGNOTE_APP_SUPPORT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / APP_NAME).resolve()
    return (Path.home() / f".{APP_NAME.lower()}").resolve()


def _default_db_path(runtime_mode: RuntimeMode, app_support_dir: Path) -> Path:
    if runtime_mode == "packaged":
        return app_support_dir / "notes.db"
    return DEFAULT_DB_PATH


def _default_frontend_dist_dir(resource_root: Path) -> Path:
    override = os.getenv("COGNOTE_FRONTEND_DIST_DIR")
    if override:
        return Path(override).expanduser().resolve()

    candidates = (
        resource_root / "frontend" / "dist",
        resource_root / "dist",
        BASE_DIR / "frontend" / "dist",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _default_exports_root_dir(runtime_mode: RuntimeMode, source_root: Path, app_support_dir: Path) -> Path:
    override = os.getenv("COGNOTE_EXPORTS_ROOT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if runtime_mode == "packaged":
        return (app_support_dir / "exports").resolve()
    return (source_root / "notes-export").resolve()


def _default_logs_dir(runtime_mode: RuntimeMode, source_root: Path, app_support_dir: Path) -> Path:
    override = os.getenv("COGNOTE_LOGS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if runtime_mode == "packaged":
        return (app_support_dir / "logs").resolve()
    return (source_root / "logs").resolve()


def _default_exporter_script_path(resource_root: Path, source_root: Path) -> Path:
    override = os.getenv("COGNOTE_EXPORTER_SCRIPT_PATH")
    if override:
        return Path(override).expanduser().resolve()

    candidates = (
        resource_root / "resources" / "apple_notes_exporter_v4.py",
        resource_root / "apple_notes_exporter_v4.py",
        resource_root / "backend" / "resources" / "apple_notes_exporter_v4.py",
        source_root / "apple_notes_exporter_v4.py",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _resolve_openai_api_key(runtime_mode: RuntimeMode) -> tuple[str | None, OpenAIKeySource]:
    env_value = (os.getenv("OPENAI_API_KEY") or "").strip()
    if env_value:
        return env_value, "env"
    if runtime_mode == "packaged":
        keychain_value = get_openai_api_key()
        if keychain_value:
            return keychain_value, "keychain"
    return None, "none"


@dataclass(frozen=True)
class Settings:
    runtime_mode: RuntimeMode
    source_root: Path
    resource_root: Path
    app_support_dir: Path
    db_path: Path
    frontend_dist_dir: Path
    exports_root_dir: Path
    logs_dir: Path
    exporter_script_path: Path
    openai_api_key: str | None
    openai_api_key_source: OpenAIKeySource
    openai_embedding_model: str
    openai_chat_model: str
    openai_search_model: str
    cors_origins: list[str]
    semantic_candidate_limit: int
    semantic_min_score: float
    related_note_limit: int
    embedding_batch_size: int

    @property
    def is_packaged(self) -> bool:
        return self.runtime_mode == "packaged"


def clear_settings_cache() -> None:
    get_settings.cache_clear()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    runtime_mode = _runtime_mode()
    app_support_dir = _default_app_support_dir()
    resource_root = _resource_root()
    openai_api_key, openai_api_key_source = _resolve_openai_api_key(runtime_mode)
    db_path = Path(
        os.getenv("NOTES_DB_PATH", str(_default_db_path(runtime_mode, app_support_dir)))
    ).expanduser().resolve()
    return Settings(
        runtime_mode=runtime_mode,
        source_root=BASE_DIR,
        resource_root=resource_root,
        app_support_dir=app_support_dir,
        db_path=db_path,
        frontend_dist_dir=_default_frontend_dist_dir(resource_root),
        exports_root_dir=_default_exports_root_dir(runtime_mode, BASE_DIR, app_support_dir),
        logs_dir=_default_logs_dir(runtime_mode, BASE_DIR, app_support_dir),
        exporter_script_path=_default_exporter_script_path(resource_root, BASE_DIR),
        openai_api_key=openai_api_key,
        openai_api_key_source=openai_api_key_source,
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        openai_search_model=os.getenv("OPENAI_SEARCH_MODEL", "gpt-4o-mini-search-preview"),
        cors_origins=_split_csv(os.getenv("BACKEND_CORS_ORIGINS")),
        semantic_candidate_limit=int(os.getenv("SEMANTIC_CANDIDATE_LIMIT", "250")),
        semantic_min_score=max(0.0, min(1.0, _env_float("SEMANTIC_MIN_SCORE", 0.64))),
        related_note_limit=int(os.getenv("RELATED_NOTE_LIMIT", "6")),
        embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "50")),
    )
