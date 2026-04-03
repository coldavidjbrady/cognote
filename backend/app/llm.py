from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .config import Settings


ASSISTANT_SYSTEM_PROMPT = """You are a helpful assistant inside a local note-taking application.

When note context is provided:
- Ground your answer in the supplied notes.
- Say clearly when the notes do not contain enough information.
- Do not invent facts that are not supported by the notes.
- Treat the provided notes as retrieved context and synthesize across them when helpful.

When no note context is provided:
- Answer as a normal general-purpose assistant.

When live, current, or rapidly changing information is needed:
- Use web search when available.
- Prefer concise answers and include source-backed claims.

Keep answers concise, practical, and easy to scan.
"""

CURRENT_INFO_PATTERN = re.compile(
    r"\b("
    r"today|tonight|this morning|this afternoon|this evening|now|current|currently|"
    r"latest|recent|recently|headline|headlines|news|weather|forecast|price|prices|"
    r"stock|stocks|score|scores|schedule|schedules|traffic|election|breaking"
    r")\b",
    re.IGNORECASE,
)

NEWS_QUERY_PATTERN = re.compile(
    r"\b("
    r"headline|headlines|news|breaking|what happened|latest in|latest on|"
    r"top stories|current events|today in|today's"
    r")\b",
    re.IGNORECASE,
)

TRUSTED_NEWS_DOMAINS = [
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "npr.org",
    "nytimes.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "cnn.com",
    "abcnews.go.com",
]


@dataclass
class AssistantResult:
    answer: str
    model: str
    response_id: str | None
    used_web_search: bool
    web_sources: list[dict[str, str]]


class LLMService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self._settings.openai_api_key)

    @property
    def model(self) -> str:
        return self._settings.openai_chat_model

    @property
    def search_model(self) -> str:
        return self._settings.openai_search_model

    def _get_client(self):
        if not self.enabled:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._settings.openai_api_key)
        return self._client

    def _build_instructions(self, mode: str, context_text: str | None = None) -> str:
        mode_instruction = (
            "Mode: note-grounded chat. Use the supplied notes as your primary grounding context. "
            "You may use web search for current external facts when helpful, but do not ignore the note context."
            if mode == "note"
            else "Mode: general chat. No note context is attached for this conversation. "
            "Do not refer to notes or claim notes were provided."
        )
        if context_text and context_text.strip():
            return (
                f"{ASSISTANT_SYSTEM_PROMPT}\n\n"
                f"{mode_instruction}\n\n"
                "Note context is available below. Use it as retrieved grounding material for every turn.\n\n"
                f"{context_text.strip()}"
            )
        return f"{ASSISTANT_SYSTEM_PROMPT}\n\n{mode_instruction}"

    def _response_to_dict(self, response: Any) -> dict[str, Any]:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "to_dict"):
            return response.to_dict()
        return {}

    def _collect_sources(self, payload: Any) -> tuple[bool, list[dict[str, str]]]:
        sources: list[dict[str, str]] = []
        used_web_search = False
        seen_urls: set[str] = set()

        def walk(value: Any) -> None:
            nonlocal used_web_search
            if isinstance(value, dict):
                item_type = value.get("type")
                if isinstance(item_type, str) and "web_search" in item_type:
                    used_web_search = True
                url = value.get("url")
                title = value.get("title")
                if isinstance(url, str) and url and url not in seen_urls:
                    seen_urls.add(url)
                    sources.append({"url": url, "title": title or url})
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(payload)
        return used_web_search, sources

    def _should_offer_web_search(self, question: str) -> bool:
        return bool(CURRENT_INFO_PATTERN.search(question))

    def _is_news_query(self, question: str) -> bool:
        return bool(NEWS_QUERY_PATTERN.search(question))

    def _should_force_live_search(self, question: str, mode: str) -> bool:
        if mode != "general":
            return False
        return self._should_offer_web_search(question) or self._is_news_query(question)

    def _answer_with_search_model(
        self,
        question: str,
        mode: str,
        history: list[dict[str, str]] | None = None,
    ) -> AssistantResult:
        client = self._get_client()
        completion = client.chat.completions.create(
            model=self.search_model,
            web_search_options={
                "user_location": {
                    "type": "approximate",
                    "approximate": {
                        "country": "US",
                        "region": "California",
                        "city": "San Francisco",
                    },
                },
            },
            messages=[
                {"role": "system", "content": self._build_instructions(mode)},
                *[
                    {"role": item["role"], "content": item["content"]}
                    for item in (history or [])
                ],
                {"role": "user", "content": question},
            ],
        )
        answer = ""
        if completion.choices:
            answer = completion.choices[0].message.content or ""
        return AssistantResult(
            answer=answer.strip() or "I couldn't generate a response for that request.",
            model=self.search_model,
            response_id=None,
            used_web_search=True,
            web_sources=[],
        )

    def answer_question(
        self,
        question: str,
        mode: str,
        history: list[dict[str, str]] | None = None,
        context_text: str | None = None,
        allow_web_search: bool = False,
        previous_response_id: str | None = None,
    ) -> AssistantResult:
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("Question cannot be empty.")

        if self._should_force_live_search(clean_question, mode):
            return self._answer_with_search_model(
                clean_question,
                mode=mode,
                history=history,
            )

        if previous_response_id:
            input_items: list[dict[str, str]] = [{"role": "user", "content": clean_question}]
        else:
            input_items = [{"role": item["role"], "content": item["content"]} for item in (history or [])]
            input_items.append({"role": "user", "content": clean_question})

        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": self._build_instructions(mode, context_text),
            "input": input_items,
        }
        if previous_response_id:
            request_kwargs["previous_response_id"] = previous_response_id

        if allow_web_search:
            web_tool: dict[str, Any] = {
                "type": "web_search",
                "user_location": {
                    "type": "approximate",
                    "country": "US",
                    "timezone": "America/Los_Angeles",
                },
            }
            if self._is_news_query(clean_question):
                web_tool["filters"] = {"allowed_domains": TRUSTED_NEWS_DOMAINS}

            request_kwargs["tools"] = [web_tool]
            request_kwargs["tool_choice"] = "auto"
            request_kwargs["include"] = ["web_search_call.action.sources"]

        client = self._get_client()
        try:
            response = client.responses.create(**request_kwargs)
        except Exception:
            request_kwargs.pop("tools", None)
            request_kwargs.pop("tool_choice", None)
            request_kwargs.pop("include", None)
            response = client.responses.create(**request_kwargs)

        response_payload = self._response_to_dict(response)
        used_web_search, web_sources = self._collect_sources(response_payload)
        answer = getattr(response, "output_text", "") or ""
        if not answer.strip():
            answer = "I couldn't generate a response for that request."
        return AssistantResult(
            answer=answer.strip(),
            model=self.model,
            response_id=getattr(response, "id", None),
            used_web_search=used_web_search,
            web_sources=web_sources,
        )
