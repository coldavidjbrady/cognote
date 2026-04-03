from __future__ import annotations

import html
import math
import re
import sqlite3
from typing import Any

from .config import Settings
from .db import (
    get_embeddings,
    get_note_embedding,
    get_recent_notes,
    keyword_search,
    rows_to_dicts,
)
from .embeddings import EmbeddingService

QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "find",
    "for",
    "from",
    "i",
    "in",
    "is",
    "looking",
    "me",
    "my",
    "note",
    "notes",
    "of",
    "on",
    "or",
    "related",
    "show",
    "that",
    "the",
    "to",
    "want",
    "with",
}


def _safe_snippet(value: str | None) -> str:
    if not value:
        return ""
    escaped = html.escape(value)
    return escaped.replace("[[mark]]", "<mark>").replace("[[/mark]]", "</mark>")


def _normalize_keyword_score(rank_index: int) -> float:
    return 1.0 / (rank_index + 1)


def _query_tokens(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", query.lower()) if token]


def _keyword_query_variants(query: str) -> list[str]:
    variants: list[str] = []

    def add_variant(value: str) -> None:
        clean = value.strip()
        if clean and clean not in variants:
            variants.append(clean)

    add_variant(query)
    tokens = _query_tokens(query)
    if not tokens:
        return variants

    focused_tokens = [token for token in tokens if token not in QUERY_STOPWORDS and len(token) >= 3]
    search_tokens = focused_tokens or [token for token in tokens if len(token) >= 2]
    if not search_tokens:
        return variants

    # When users type natural language, keep semantically dense terms
    # and progressively widen matching in FTS.
    add_variant(" ".join(search_tokens))
    if len(search_tokens) > 1:
        add_variant(" OR ".join(search_tokens))

    if len(search_tokens) >= 2:
        # Helps cases like "wi fi" matching notes that contain "wifi".
        add_variant("".join(search_tokens))

    for token in search_tokens:
        add_variant(token)

    return variants


def _keyword_search_with_fallbacks(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    collection_id: int | None = None,
) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for candidate in _keyword_query_variants(query):
        try:
            rows = keyword_search(conn, candidate, limit=limit, collection_id=collection_id)
        except sqlite3.OperationalError:
            # Some raw natural-language forms are not valid FTS syntax.
            # Continue through normalized fallback variants.
            continue
        for item in rows:
            merged[int(item["id"])] = item
        if len(merged) >= limit:
            break
    if len(merged) < limit:
        # Final fallback: normalize punctuation/casing so WiFi can match wi-fi.
        for item in _loose_keyword_matches(
            conn,
            query=query,
            limit=limit - len(merged),
            collection_id=collection_id,
            exclude_note_ids=set(merged.keys()),
        ):
            merged[int(item["id"])] = item
    return list(merged.values())[:limit]


def _normalize_loose_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _loose_keyword_matches(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    collection_id: int | None,
    exclude_note_ids: set[int],
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    tokens = [token for token in _query_tokens(query) if token not in QUERY_STOPWORDS and len(token) >= 3]
    if not tokens:
        return []

    normalized_tokens = [_normalize_loose_match_text(token) for token in tokens]
    normalized_tokens = [token for token in normalized_tokens if token]
    if not normalized_tokens:
        return []

    sql = """
        SELECT
            n.id,
            n.title,
            n.folder,
            n.account,
            n.source_modified_at AS modified_at_display,
            n.modified_at_iso,
            substr(n.body_text, 1, 220) AS snippet
        FROM notes n
    """
    params: list[Any] = []
    if collection_id is not None:
        sql += " JOIN collection_notes cn ON cn.note_id = n.id WHERE cn.collection_id = ?"
        params.append(collection_id)
    sql += """
        ORDER BY
            CASE WHEN n.modified_at_iso IS NULL THEN 1 ELSE 0 END,
            n.modified_at_iso DESC,
            n.imported_at DESC
        LIMIT 500
    """
    rows = conn.execute(sql, tuple(params)).fetchall()
    candidates = rows_to_dicts(rows)

    scored: list[dict[str, Any]] = []
    for item in candidates:
        note_id = int(item["id"])
        if note_id in exclude_note_ids:
            continue
        normalized_title = _normalize_loose_match_text(item.get("title") or "")
        normalized_snippet = _normalize_loose_match_text(item.get("snippet") or "")
        text = f"{normalized_title} {normalized_snippet}"
        token_hits = sum(1 for token in normalized_tokens if token in text)
        if token_hits <= 0:
            continue
        item["raw_score"] = float(-token_hits)
        scored.append(item)

    scored.sort(key=lambda row: row["raw_score"])
    return scored[:limit]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def semantic_search(
    conn: sqlite3.Connection,
    settings: Settings,
    embedding_service: EmbeddingService,
    query: str,
    limit: int = 20,
    collection_id: int | None = None,
) -> list[dict[str, Any]]:
    if not embedding_service.enabled or not query.strip():
        return []

    query_vector = embedding_service.embed_text(query.strip())
    if not query_vector:
        return []

    candidates = get_embeddings(
        conn,
        collection_id=collection_id,
    )
    scored: list[dict[str, Any]] = []
    for item in candidates:
        similarity = cosine_similarity(query_vector, item["vector"])
        item["semantic_score"] = (similarity + 1) / 2
        if item["semantic_score"] < settings.semantic_min_score:
            continue
        item["snippet"] = _safe_snippet(item.get("snippet"))
        item["match_type"] = "semantic"
        scored.append(item)

    scored.sort(key=lambda item: item["semantic_score"], reverse=True)
    return scored[:limit]


def hybrid_search(
    conn: sqlite3.Connection,
    settings: Settings,
    embedding_service: EmbeddingService,
    query: str,
    mode: str = "hybrid",
    limit: int = 20,
    collection_id: int | None = None,
) -> list[dict[str, Any]]:
    clean_query = query.strip()
    if not clean_query:
        items = get_recent_notes(conn, limit=limit, collection_id=collection_id)
        for item in items:
            item["snippet"] = _safe_snippet(item.get("snippet"))
        return items

    keyword_results: list[dict[str, Any]] = []
    if mode in {"hybrid", "keyword"}:
        try:
            keyword_results = _keyword_search_with_fallbacks(
                conn,
                clean_query,
                limit=max(limit * 3, 30),
                collection_id=collection_id,
            )
        except sqlite3.OperationalError:
            keyword_results = []

    semantic_results: list[dict[str, Any]] = []
    if mode in {"hybrid", "semantic"}:
        semantic_results = semantic_search(
            conn,
            settings,
            embedding_service,
            clean_query,
            limit=max(limit * 3, 30),
            collection_id=collection_id,
        )

    if mode == "keyword":
        for index, item in enumerate(keyword_results):
            item["score"] = _normalize_keyword_score(index)
            item["snippet"] = _safe_snippet(item.get("snippet"))
            item["match_type"] = "keyword"
        return keyword_results[:limit]

    if mode == "semantic":
        return semantic_results[:limit]

    merged: dict[int, dict[str, Any]] = {}

    for index, item in enumerate(keyword_results):
        note_id = int(item["id"])
        merged[note_id] = {
            **item,
            "keyword_score": _normalize_keyword_score(index),
            "semantic_score": 0.0,
            "snippet": _safe_snippet(item.get("snippet")),
            "match_type": "keyword",
        }

    for item in semantic_results:
        note_id = int(item["id"])
        current = merged.get(note_id)
        if current is None:
            merged[note_id] = {
                **item,
                "keyword_score": 0.0,
                "semantic_score": item["semantic_score"],
                "match_type": "semantic",
            }
        else:
            current["semantic_score"] = item["semantic_score"]
            if current.get("match_type") == "keyword":
                current["match_type"] = "hybrid"

    ranked = []
    for item in merged.values():
        item["score"] = (item.get("keyword_score", 0.0) * 0.58) + (
            item.get("semantic_score", 0.0) * 0.42
        )
        ranked.append(item)

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


def related_notes(
    conn: sqlite3.Connection,
    note_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    base_vector = get_note_embedding(conn, note_id)
    if not base_vector:
        items = get_recent_notes(conn, limit=limit + 1)
        return [item for item in items if item["id"] != note_id][:limit]

    candidates = get_embeddings(conn, exclude_note_id=note_id)
    for item in candidates:
        similarity = cosine_similarity(base_vector, item["vector"])
        item["semantic_score"] = (similarity + 1) / 2
        item["snippet"] = _safe_snippet(item.get("snippet"))
        item["match_type"] = "related"

    candidates.sort(key=lambda item: item["semantic_score"], reverse=True)
    return candidates[:limit]
