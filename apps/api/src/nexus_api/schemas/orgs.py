"""Request and response models for organization trees, people in nodes and space bindings."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class UnitCreate(BaseModel):
    parent_id: UUID
    name: str = Field(min_length=1, max_length=160)


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: UUID | None = None
    status: Literal["active", "disabled"] | None = None


class MemberLink(BaseModel):
    is_primary: bool = False


class OrgView(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime


class NodeView(BaseModel):
    id: UUID
    parent_id: UUID | None
    name: str
    status: str
    member_count: int = 0


class UnitView(BaseModel):
    id: UUID
    root_id: UUID
    parent_id: UUID | None
    name: str
    status: str


class LinkView(BaseModel):
    user_id: UUID
    unit_id: UUID
    is_primary: bool


class UnitMembership(BaseModel):
    unit_id: UUID
    unit_name: str
    is_primary: bool


class PersonView(BaseModel):
    user_id: UUID
    display_name: str | None
    units: list[UnitMembership]


class BoundNode(BaseModel):
    id: UUID
    parent_id: UUID | None
    name: str
    status: str


class BindingView(BaseModel):
    unit_id: UUID
    unit_name: str
    organization_name: str
    status: str
    nodes: list[BoundNode]


class SpaceOrganizationView(BaseModel):
    bindings: list[BindingView]
    people: list[PersonView]


class JoinFromOrganization(BaseModel):
    user_ids: list[UUID] = Field(min_length=1, max_length=500)
    role: Literal["admin", "member"] = "member"


class JoinResult(BaseModel):
    added: list[UUID]
    skipped: list[UUID]
