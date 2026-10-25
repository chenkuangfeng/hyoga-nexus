"""Persistence of one input response, serialized by the containing Run's lock."""
from datetime import datetime
from uuid import UUID
from sqlalchemy.orm import Session
from nexus_platform.persistence.models import InputRequestRecord
from .domain import PendingInput


class SqlAlchemyRunInputRepository:
    """Return consumption state by value and write only requests already loaded in this scope."""
    def __init__(self, session: Session):
        self.session = session
        self._requests: dict[UUID, InputRequestRecord] = {}

    def get(self, request_id: UUID) -> PendingInput | None:
        """Read state; the application must validate its Run association before consuming it."""
        row = self.session.get(InputRequestRecord, request_id)
        if row is None:
            return None
        self._requests[row.id] = row
        return PendingInput(row.id, row.run_id, row.response, row.response_key, row.responded_at)

    def consume(self, request_id: UUID, response: str, key: str, at: datetime) -> None:
        row = self._requests[request_id]
        row.response, row.response_key, row.responded_at = response, key, at
