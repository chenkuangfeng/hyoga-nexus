"""Request models for sharing enterprise agents with shared spaces."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AgentShareCreate(BaseModel):
    shared_space_id: UUID
    level: Literal["viewer", "editor", "admin"] = "viewer"
