from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    color: str = Field(default="#315c4a", min_length=4, max_length=16)
    note_ids: list[int] = Field(default_factory=list)


class CollectionNoteAdd(BaseModel):
    note_id: int


class NoteLinkCreate(BaseModel):
    source_note_id: int
    target_note_id: int
    relationship_type: str = Field(default="related", min_length=1, max_length=40)
    note: str = Field(default="", max_length=240)


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class AssistantQuery(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    mode: Literal["general", "note"] = "general"
    note_id: int | None = None
    include_linked_notes: bool = True
    history: list[AssistantMessage] = Field(default_factory=list)
    previous_response_id: str | None = None
