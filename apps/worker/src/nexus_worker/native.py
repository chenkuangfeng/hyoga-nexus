"""Application composition root for Native execution."""
from __future__ import annotations

import asyncio
import os
import re
from contextlib import suppress
from datetime import timedelta
from dataclasses import fields

from nexus_core.platform import utc_now
from nexus_core.native import NativePolicy
from nexus_core.runtime import ExecutionBudget, RuntimeFault, RuntimeOutcome, ToolDefinition, ToolDisposition, ToolResult
from nexus_platform.models.ports import CredentialLease
from nexus_platform.models.provider_settings import StoredCredentialResolver
from nexus_platform.errors import PlatformError
from nexus_runtimes.native.models.network import provider_client
from nexus_runtimes.native.models.factory import create_model
from nexus_platform.runs.execution import DurableRuntimeStore, prepare_execution
from nexus_runtimes.native.engine import CancellationToken, NativeEngine
from nexus_runtimes.native.models.openai_compatible import OpenAICompatibleModel
from nexus_tools.gateway import AuthorizedToolGateway
from nexus_tools.builtins import builtins


class EnvironmentCredentialResolver:
    """Only explicitly allowed handles may be resolved, never arbitrary process variables."""
    def resolve(self, reference, *, principal_id, run_id):
        allowed = {name.strip() for name in os.getenv('NEXUS_MODEL_CREDENTIAL_ALLOWLIST', '').split(',') if name.strip()}
        name = reference.handle.removeprefix('env://')
        if reference.backend != 'environment' or not reference.handle.startswith('env://') or name not in allowed or not re.fullmatch(r'[A-Z_][A-Z0-9_]*', name):
            raise RuntimeFault('model_credential_unavailable')
        value = os.getenv(name)
        if not value:
            raise RuntimeFault('model_credential_unavailable')
        return CredentialLease(value, utc_now() + timedelta(minutes=5))


def configured_model(context, resolver):
    """Resolve this Run's short-lived credential and construct its controlled model client.

    Only explicit Chat Completions configuration is supported. Missing/expired credentials
    produce a stable RuntimeFault; platform/storage errors never expose secret diagnostics.
    """
    if context.runtime_type != 'native' or context.options.get('protocol') not in ('openai_chat_completions', 'openai_responses', 'anthropic_messages'):
        raise RuntimeFault('runtime_not_configured')
    if not context.credential:
        raise RuntimeFault('model_credential_unavailable')
    try:
        lease = resolver.resolve(context.credential, principal_id=context.principal_id, run_id=context.run_id)
    except PlatformError:
        raise RuntimeFault('model_credential_unavailable') from None
    if lease.expires_at <= utc_now():
        raise RuntimeFault('model_credential_unavailable')
    return create_model(model=context.model_name, api_key=lease.reveal_for_call(), options=context.options)




class ToolAccess:
    def __init__(self, store):
        self.authorize, self.start, self.denied = store.authorize, store.start, store.denied
        self.finish = store.finish_tool
        self.progress = store.tool_progress
        self.approval = store.approval


#: Delay before a deferred delivery is offered again. Other sessions are not affected.
DEFER_SECONDS = 2


def admit_or_defer(factory, epoch: int, task_id, worker_id: str) -> bool:
    """Gate one ``run.execute`` delivery on its session FIFO before the Run starts.

    Returns True when the Run may start (its admission is now claimed, or it needs no gate).
    Returns False when the Run is queued behind another Run or the session is blocked: the
    Outbox lease is released and the delivery is offered again after ``DEFER_SECONDS``. The Run
    stays ``queued`` and no failure is written.
    """
    from datetime import timedelta
    from nexus_platform.persistence.models.queue import OutboxRecord
    from nexus_platform.persistence.models.run import RunRecord
    from nexus_platform.runs import session_ledger as ledger
    now = utc_now()
    with factory() as db:
        task = db.get(OutboxRecord, task_id)
        if task is None or task.message_type != 'run.execute' or task.lease_owner != worker_id:
            return True
        run = db.get(RunRecord, task.run_id)
        if run is None:
            return True
        if ledger.claim_run(db, epoch=epoch, run_id=run.id, session_id=run.session_id, now=now):
            db.commit()
            return True
        task.lease_owner, task.lease_until = None, None
        task.available_at = now + timedelta(seconds=DEFER_SECONDS)
        db.commit()
        return False


async def execute_native(factory, task_id, worker_id, *, model_factory=None, registry_factory=None,
                         resolver=None, hooks=(), stopped=None, ledger_epoch=None):
    if ledger_epoch is not None and not admit_or_defer(factory, ledger_epoch, task_id, worker_id):
        return
    context = prepare_execution(factory, task_id, worker_id)
    if context is None:
        return
    store = DurableRuntimeStore(factory, context, worker_id, task_id)
    token = CancellationToken()
    monitor_error = None
    async def monitor():
        nonlocal monitor_error
        while True:
            try:
                if (stopped and stopped.is_set()) or store.heartbeat():
                    token.cancel()
                    return
            except Exception:
                monitor_error = 'interrupted'
                token.cancel()
                return
            await asyncio.sleep(0.2)
    monitor_task = asyncio.create_task(monitor())
    model = None
    try:
        if model_factory:
            model = model_factory(context)
        else:
            from .models import configured_routing
            model = configured_routing(context, factory, resolver or StoredCredentialResolver(factory, EnvironmentCredentialResolver()))
        if context.runtime_type != 'native':
            raise RuntimeFault('runtime_not_configured')
        registry = (registry_factory or builtins)(store)
        gateway = AuthorizedToolGateway(registry, ToolAccess(store),
            {name: version for name, version, _ in context.bindings}, run_id=str(context.run_id),
            session_id=str(context.session_id), tenant_id=str(context.tenant_id))
        names = {field.name for field in fields(ExecutionBudget)}
        options = {key: value for key, value in context.budgets.items() if key in names}
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in options.values()):
            raise RuntimeFault('runtime_budget_invalid')
        if any(not isinstance(options.get(key, 1), int) for key in
               ('max_rounds', 'max_tokens', 'max_output_tokens', 'max_errors', 'max_context_chars')):
            raise RuntimeFault('runtime_budget_invalid')
        try:
            budget = ExecutionBudget(**options)
        except ValueError:
            raise RuntimeFault('runtime_budget_invalid') from None
        try:
            policy = NativePolicy(**context.budgets.get('behavior', {}))
        except (ValueError, TypeError):
            raise RuntimeFault('runtime_budget_invalid') from None
        outcome = await NativeEngine(model, gateway, store, hooks=hooks, policy=policy).run(
            str(context.run_id), context.messages, token, budget, context.progress)
    except RuntimeFault as exc:
        outcome = RuntimeOutcome('interrupted' if exc.code == 'interrupted' else 'failed', exc.code)
    except Exception:
        outcome = RuntimeOutcome('failed', 'runtime_error')
    finally:
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        if model:
            with suppress(Exception):
                await model.close()
    if monitor_error:
        outcome = RuntimeOutcome('interrupted', monitor_error)
    store.finish(outcome)
