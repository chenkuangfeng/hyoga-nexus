"""SQLAlchemy reads for submission configuration; published values leave as independent copies."""
from copy import deepcopy
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_platform.persistence.models import (
    AgentRecord, AgentVersionRecord, ModelProfileRecord, ModelProfileVersionRecord,
    ResourceBindingRecord, SessionRecord,
)
from .configuration import BoundResource, PublishedAgent, PublishedModel, SubmissionSession


class SqlAlchemySubmissionCatalog:
    """Load only the configuration needed by submission, preserving the original lock order."""
    def __init__(self, session: Session):
        self.session = session
        self._sessions: dict[UUID, SessionRecord] = {}

    def owned_session(self, workspace_id: UUID, user_id: UUID, session_id: UUID) -> SubmissionSession | None:
        """Lock the caller's Session in the selected workspace; foreign rows are invisible."""
        row = self.session.scalar(select(SessionRecord).where(
            SessionRecord.id == session_id, SessionRecord.workspace_id == workspace_id,
            SessionRecord.owner_user_id == user_id,
        ).with_for_update())
        if row is None:
            return None
        self._sessions[row.id] = row
        return SubmissionSession(row.id, row.agent_version_id, row.status)

    def agent_version(self, version_id: UUID) -> PublishedAgent | None:
        row = self.session.get(AgentVersionRecord, version_id)
        if row is None:
            return None
        return PublishedAgent(row.id, row.agent_id, row.version, row.content_hash, row.runtime_type,
                              row.model_profile_version_id, deepcopy(row.budgets))

    def agent_workspace(self, agent_id: UUID) -> UUID | None:
        row = self.session.get(AgentRecord, agent_id)
        return row.workspace_id if row is not None else None

    def bindings(self, version_id: UUID) -> list[BoundResource]:
        return [BoundResource(row.id, row.kind, row.resource_id, row.resource_version_id,
                              row.source_workspace_id, deepcopy(row.binding_config))
                for row in self.session.scalars(select(ResourceBindingRecord).where(
                    ResourceBindingRecord.agent_version_id == version_id))]

    def model_version(self, version_id: UUID) -> PublishedModel | None:
        row = self.session.get(ModelProfileVersionRecord, version_id)
        if row is None:
            return None
        return PublishedModel(row.id, row.profile_id, row.content_hash, row.credential_reference_id)

    def model_workspace(self, profile_id: UUID) -> UUID | None:
        row = self.session.get(ModelProfileRecord, profile_id)
        return row.workspace_id if row is not None else None

    def touch_session(self, session_id: UUID, at: datetime) -> None:
        """Update only a Session already locked through this catalog; never acquire an unscoped row."""
        self._sessions[session_id].updated_at = at
