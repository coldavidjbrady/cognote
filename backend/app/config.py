from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
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


@dataclass(frozen=True)
class Settings:
    db_path: Path
    openai_api_key: str | None
    openai_embedding_model: str
    openai_chat_model: str
    openai_search_model: str
    cors_origins: list[str]
    semantic_candidate_limit: int
    semantic_min_score: float
    related_note_limit: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    db_path = Path(os.getenv("NOTES_DB_PATH", str(DEFAULT_DB_PATH))).expanduser().resolve()
    return Settings(
        db_path=db_path,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        openai_search_model=os.getenv("OPENAI_SEARCH_MODEL", "gpt-4o-mini-search-preview"),
        cors_origins=_split_csv(os.getenv("BACKEND_CORS_ORIGINS")),
        semantic_candidate_limit=int(os.getenv("SEMANTIC_CANDIDATE_LIMIT", "250")),
        semantic_min_score=max(0.0, min(1.0, _env_float("SEMANTIC_MIN_SCORE", 0.64))),
        related_note_limit=int(os.getenv("RELATED_NOTE_LIMIT", "6")),
    )
