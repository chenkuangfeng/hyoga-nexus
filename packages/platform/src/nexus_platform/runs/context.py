"""Durable execution context; model execution stays in runtimes."""
from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID
from nexus_core.platform import CredentialRef, Principal
from nexus_core.runtime import ModelMessage, RuntimeProgress
from nexus_core.runtime.context import ContextBlock


@dataclass(frozen=True)
class ExecutionContext:
    run_id: UUID
    session_id: UUID
    tenant_id: UUID
    principal_id: UUID
    principal: Principal
    runtime_type: str
    provider: str
    model_name: str
    options: dict
    credential: CredentialRef | None
    messages: tuple[ModelMessage, ...]
    bindings: tuple[tuple[str, str, str], ...]
    budgets: dict
    progress: RuntimeProgress
    history_run_ids: tuple[UUID, ...]
    #: MCP service ids bound to the agent version (from the frozen config snapshot). Resolved live at execution.
    mcp_service_ids: tuple[str, ...] = ()

    #: Authorized, named contributions; worker renders these with the pure request assembler.
    context_blocks: tuple[ContextBlock, ...] = ()
    source_watermark: int = 0
