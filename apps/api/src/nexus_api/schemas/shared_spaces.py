"""Request models for shared spaces (WeKnora organizations, named shared spaces here)."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SharedRole = Literal["admin", "editor", "viewer"]


class SharedSpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


class SharedSpaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    require_approval: bool | None = None
    searchable: bool | None = None
    member_limit: int | None = Field(default=None, ge=1, le=10000)
    invite_code_validity_days: int | None = Field(default=None, ge=1, le=365)


class InviteCodeJoin(BaseModel):
    invite_code: str = Field(min_length=4, max_length=64)


class JoinById(BaseModel):
    shared_space_id: UUID


class JoinRequestCreate(BaseModel):
    shared_space_id: UUID
    requested_role: SharedRole = "viewer"
    message: str = Field(default="", max_length=500)


class UpgradeRequest(BaseModel):
    requested_role: SharedRole
    message: str = Field(default="", max_length=500)


class ReviewRequest(BaseModel):
    review_message: str = Field(default="", max_length=500)
