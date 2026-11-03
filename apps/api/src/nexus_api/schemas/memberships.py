"""Request models for members, invitations, join applications and leaving a space."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

InvitableRole = Literal["admin", "contributor", "viewer"]


class MemberByEmail(BaseModel):
    """Add a person by email. An existing account is invited; a new email creates the account, which then
    needs `username` and a temporary `password` (the person must change it on first sign-in)."""
    email: str = Field(min_length=3, max_length=255)
    role: InvitableRole = "contributor"
    unit_id: UUID | None = None
    username: str | None = Field(default=None, min_length=3, max_length=64)
    password: str | None = Field(default=None, min_length=10, max_length=256)
    display_name: str = Field(default="", max_length=160)


class ApplicationCreate(BaseModel):
    message: str = Field(default="", max_length=500)


class ApplicationApprove(BaseModel):
    unit_id: UUID
    role: InvitableRole = "contributor"


class ApplicationReject(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RoleToUnit(BaseModel):
    role_id: UUID


class InviteLinkCreate(BaseModel):
    """A share link: anyone signed in who opens it joins with `role`, until it expires (1-30 days)."""

    role: InvitableRole = "contributor"
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InviteToken(BaseModel):
    token: str = Field(min_length=1, max_length=128)
