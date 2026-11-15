"""Request and response models for an enterprise's organization tree (机构管理) and its members' positions."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UnitCreate(BaseModel):
    """`parent_id` omitted creates the enterprise root, which can only be created once."""
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=160)


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: UUID | None = None
    status: Literal["active", "disabled"] | None = None


class NodeView(BaseModel):
    id: UUID
    parent_id: UUID | None
    name: str
    status: str
    source: str
    sync_managed: bool
    member_count: int = 0


class UnitView(BaseModel):
    id: UUID
    tenant_id: UUID
    root_id: UUID
    parent_id: UUID | None
    name: str
    status: str
    source: str
    sync_managed: bool


class MemberLink(BaseModel):
    is_primary: bool = False


class LinkView(BaseModel):
    source: Literal["manual", "wecom", "mixed"]
    user_id: UUID
    unit_id: UUID
    is_primary: bool


class UnitMemberView(BaseModel):
    source: Literal["manual", "wecom", "mixed"]
    user_id: UUID
    display_name: str | None
    is_primary: bool
