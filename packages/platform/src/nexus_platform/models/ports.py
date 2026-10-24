from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from nexus_core.platform import CredentialRef


@dataclass(frozen=True, slots=True)
class CredentialLease:
    """Short-lived in-memory secret; repr intentionally omits the resolved value."""

    _value: str = field(repr=False)
    expires_at: datetime

    def reveal_for_call(self) -> str:
        return self._value


class CredentialResolver(Protocol):
    def resolve(
        self,
        reference: CredentialRef,
        *,
        principal_id: UUID,
        run_id: UUID,
    ) -> CredentialLease: ...
