"""Ordered submission/input messages in the caller's transaction and Session lock."""
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from nexus_core.platform import new_id
from nexus_core.runtime import ModelMessage
from nexus_platform.persistence.models import MessageRecord
from .domain import Run
from .messages import add_message


class SqlAlchemyRunMessageRepository:
    """Retain initial-message metadata and explicit user-input provenance as distinct paths."""
    def __init__(self, session: Session):
        self.session = session

    def initial(self, run: Run, content: str, at: datetime) -> None:
        """Append under the submission Session lock with the original empty runtime metadata."""
        sequence = self.session.scalar(select(func.coalesce(func.max(MessageRecord.sequence), 0)).where(
            MessageRecord.session_id == run.session_id,
        )) + 1
        self.session.add(MessageRecord(
            id=new_id(), session_id=run.session_id, run_id=run.id, sequence=sequence,
            role='user', content=content, created_at=at,
        ))

    def user_input(self, run: Run, content: str) -> None:
        """Use existing message allocation, Session locking and user_input metadata."""
        add_message(self.session, run, ModelMessage('user', content), origin='user_input')
