from __future__ import annotations

from typing import Iterable

from .config import Settings


class EmbeddingService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.openai_api_key)

    @property
    def model(self) -> str:
        return self._settings.openai_embedding_model

    def _get_client(self):
        if not self.enabled:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._settings.openai_api_key)
        return self._client

    def embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        payload = [text for text in texts if text and text.strip()]
        if not payload:
            return []
        client = self._get_client()
        response = client.embeddings.create(
            model=self.model,
            input=payload,
            encoding_format="float",
        )
        return [list(item.embedding) for item in response.data]

    def embed_text(self, text: str) -> list[float] | None:
        values = self.embed_texts([text])
        return values[0] if values else None
