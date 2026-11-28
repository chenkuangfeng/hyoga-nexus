"""Application composition root for Native execution."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import suppress
from datetime import timedelta
from dataclasses import fields

from nexus_core.platform import utc_now

logger = logging.getLogger("nexus_worker")
from nexus_core.native import NativePolicy
from nexus_tools.builtins.services import RunServices
from nexus_core.runtime import ExecutionBudget, RunContext, RunRequest, RuntimeFault, RuntimeOutcome, ToolDefinition, ToolDisposition, ToolResult
from nexus_platform.configuration import DatabaseConfigurationError, model_credentials
from nexus_platform.models.ports import CredentialLease
from nexus_platform.models.provider_settings import StoredCredentialResolver
from nexus_platform.errors import PlatformError
from nexus_runtimes.native.models.network import provider_client
from nexus_runtimes.native.models.factory import create_model
from nexus_platform.runs.dbexec import run_db
from .artifacts import register_outputs
from nexus_platform.runs.execution import DurableRuntimeStore, prepare_execution
from nexus_platform.runs.tool_gates import deployment_gate_facts, hidden_groups
from .sandbox_runtime import session_for
from .subagent import SubagentRunner
import nexus_platform.persistence.models.schedule  # noqa: F401  (registers cron_jobs with the metadata)
from nexus_runtimes.native.engine import CancellationToken, RunOrchestrator
from nexus_runtimes.native.models.openai_compatible import OpenAICompatibleModel
from nexus_tools.gateway import AuthorizedToolGateway, OutputSpill
from nexus_tools.builtins import builtins


class DeploymentCredentialResolver:
    """Only names listed in ``[model_credentials]`` in configs/nexus.toml may be resolved.

    Stored references keep the ``environment`` backend and ``env://NAME`` handle for compatibility;
    the value now comes from the deployment file, and the table itself is the allowlist.
    """
    def resolve(self, reference, *, principal_id, run_id):
        name = reference.handle.removeprefix('env://')
        if reference.backend != 'environment' or not reference.handle.startswith('env://') or not re.fullmatch(r'[A-Z_][A-Z0-9_]*', name):
            raise RuntimeFault('model_credential_unavailable')
        try:
            value = model_credentials().get(name)
        except DatabaseConfigurationError:
            raise RuntimeFault('model_credential_unavailable') from None
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
    # Connections are shared per origin; the credential is resolved and sent per Run, never pooled.
    return create_model(model=context.model_name, api_key=lease.reveal_for_call(), options=context.options,
                        share_connections=True)




class ToolAccess:
    def __init__(self, store):
        self._store = store
        self.authorize, self.start, self.denied = store.authorize, store.start, store.denied
        self.finish = store.finish_tool
        self.progress = store.tool_progress
        self.approval = store.approval
        self.grant = store.grant
        self.spill = store.spill_tool_output

    async def observe(self, invocation_id: str, kind: str, payload: dict) -> None:
        """Run event about one tool call (`tool.injection_suspected`, `tool.guard_finding`)."""
        await self._store.emit(kind, {**payload, 'invocation_id': invocation_id})


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
                         resolver=None, hooks=(), stopped=None, ledger_epoch=None, compaction_model_factory=None,
                         watchdog=None):
    # Synchronous database work runs on the database pool so the Runs sharing this event loop are not stalled.
    if ledger_epoch is not None and not await run_db(admit_or_defer, factory, ledger_epoch, task_id, worker_id):
        return
    context = await run_db(prepare_execution, factory, task_id, worker_id)
    if context is None:
        return
    store = DurableRuntimeStore(factory, context, worker_id, task_id)
    token = CancellationToken()
    monitor_error = None
    # Watchdog state lives for this Run only; a worker restart forgets it, so an open stall may be re-reported once.
    watch_alerted: set[str] = set()
    await run_db(store.stream_start)
    async def monitor():
        nonlocal monitor_error
        next_watch = 0.0
        next_check = 0.0
        while True:
            try:
                # The database lease and cancel check runs every `lease_check_seconds`; a cancel signal on the
                # run-event channel brings it forward, so cancelling is quick without a check every 0.2 s.
                due = time.monotonic() >= next_check
                if (stopped and stopped.is_set()) or (due and await run_db(store.heartbeat)):
                    token.cancel()
                    return
                if due:
                    next_check = time.monotonic() + store.lease_check_seconds
            except Exception:
                monitor_error = 'interrupted'
                token.cancel()
                return
            if watchdog is not None and time.monotonic() >= next_watch:
                next_watch = time.monotonic() + watchdog.interval_seconds
                try:
                    await run_db(store.watch, watchdog, watch_alerted)
                except Exception:
                    # Observation failures must never stop or fail the Run it observes.
                    logger.warning("Run watchdog check failed", extra={"task_id": str(task_id)}, exc_info=True)
            if await store.wait_for_signal_async(0.2):
                next_check = 0.0
    monitor_task = asyncio.create_task(monitor())
    model = None
    sandbox = None
    try:
        if model_factory:
            model = model_factory(context)
        else:
            from .models import configured_routing
            model = configured_routing(context, factory, resolver or StoredCredentialResolver(factory, DeploymentCredentialResolver()))
        if context.runtime_type != 'native':
            raise RuntimeFault('runtime_not_configured')
        # Builtin definitions are shared for the process; the Run's store reaches handlers via services.
        registry = registry_factory(store) if registry_factory else builtins()
        try:
            policy = NativePolicy(**context.budgets.get('behavior', {}))
        except (ValueError, TypeError):
            raise RuntimeFault('runtime_budget_invalid') from None
        spill = OutputSpill(policy.tool_output_inline_limit, policy.tool_preview_chars, policy.tool_output_page_chars)
        def read_gate_facts():
            with factory() as db:
                return deployment_gate_facts(db, policy.sandbox_profile)
        hidden = hidden_groups(await run_db(read_gate_facts), policy.tool_groups_enabled)
        # The session serves the sandbox tools and `exec_skill`, which is offered (see preparation) only when the
        # agent's profile is usable even if the whole sandbox group is switched off.
        needs_sandbox = 'sandbox' not in hidden or any(name == 'exec_skill' for name, _, _ in context.bindings)
        sandbox = None if not needs_sandbox else session_for(
            str(context.tenant_id), str(context.session_id), default_timeout=policy.sandbox_exec_timeout_seconds,
            output_limit=policy.sandbox_output_limit, profile=policy.sandbox_profile,
            user_id=str(context.principal_id))
        services = RunServices(store, context.progress.state, sandbox)
        tool_access = ToolAccess(store)
        bound = {name: version for name, version, _ in context.bindings}
        from nexus_platform.schedule.service import is_scheduled_session
        if await run_db(is_scheduled_session, factory, context.session_id):
            # A scheduled run has nobody to ask: no questions, no approvals (whatever needs one is refused), no new schedules.
            from .subagent import NoApprovalAccess
            tool_access = NoApprovalAccess(tool_access)
            bound = {name: version for name, version in bound.items() if name not in ('ask_user', 'cronjob_manage')}
        elif 'schedule' not in hidden:
            from .schedule import ScheduleBridge
            services.schedule = ScheduleBridge(factory, context.principal, context.tenant_id, context.session_id)
        gateway = AuthorizedToolGateway(registry, tool_access, bound, run_id=str(context.run_id),
            session_id=str(context.session_id), tenant_id=str(context.tenant_id),
            services=services, spill=spill,
            turn_budget=policy.tool_turn_budget_chars, injection_scan=policy.tool_injection_scan,
            tool_access=policy.tool_access,
            hidden_groups=hidden, defer_min_tokens=policy.tool_search_min_tokens)
        if context.mcp_service_ids:
            # MCP tools bound to the agent (openspec 2026-11-08-mcp, 1.6): projected from live service/tool/policy
            # state and registered so they flow through the same authorized gateway as builtins. Every call rechecks.
            from .mcp_tools import register_mcp_tools
            await register_mcp_tools(run_db, factory, registry, bound,
                                     tenant_id=context.tenant_id, principal_id=context.principal_id,
                                     service_ids=context.mcp_service_ids)
        names = {field.name for field in fields(ExecutionBudget)}
        options = {key: value for key, value in context.budgets.items() if key in names}
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in options.values()):
            raise RuntimeFault('runtime_budget_invalid')
        if any(not isinstance(options.get(key, 1), int) for key in
               ('max_rounds', 'max_tokens', 'max_output_tokens', 'max_errors', 'max_context_tokens', 'max_context_chars')):
            raise RuntimeFault('runtime_budget_invalid')
        try:
            budget = ExecutionBudget(**options)
        except ValueError:
            raise RuntimeFault('runtime_budget_invalid') from None
        if 'media' not in hidden and policy.vision_model_profile_version_id:
            from .vision import VisionAnalyzer
            services.vision = VisionAnalyzer(factory, context.tenant_id, context.principal_id, policy.vision_model_profile_version_id)
        if 'collab' not in hidden:
            # Delegated tasks (openspec 2026-11-07-tool-expansion 8.1): a nested run with a subset of these tools.
            from .models import configured_routing
            services.delegate = SubagentRunner(
                build_model=(lambda: model_factory(context)) if model_factory else
                (lambda: configured_routing(context, factory, resolver or StoredCredentialResolver(factory, DeploymentCredentialResolver()))),
                registry=registry, parent_bindings=bound, parent_policy=policy, hidden_groups=hidden, access=tool_access,
                services_store=store, sandbox=sandbox, token=token, parent_progress=context.progress, parent_budget=budget,
                emit=store.emit, run_id=str(context.run_id), session_id=str(context.session_id), tenant_id=str(context.tenant_id))
        if compaction_model_factory is None and policy.compaction_model_profile_version_id:
            # The summarizer is authorized per summary call; a revoked grant degrades compaction only.
            from .models import compaction_model
            version_id = policy.compaction_model_profile_version_id
            compaction_resolver = resolver or StoredCredentialResolver(factory, DeploymentCredentialResolver())
            compaction_model_factory = lambda: compaction_model(context, factory, compaction_resolver, version_id)
        runtime = RunOrchestrator(model, gateway, store, hooks=hooks, policy=policy,
                                  compaction_model_factory=compaction_model_factory)
        outcome = await runtime.run(
            RunRequest(run_id=str(context.run_id), messages=tuple(context.messages), budget=budget),
            RunContext(token=token, progress=context.progress))
    except RuntimeFault as exc:
        outcome = RuntimeOutcome('interrupted' if exc.code == 'interrupted' else 'failed', exc.code)
    except Exception:
        outcome = RuntimeOutcome('failed', 'runtime_error')
    finally:
        if sandbox is not None:
            # Background commands belong to the Run that started them (openspec 2026-11-07-tool-expansion 4.7).
            with suppress(Exception):
                await sandbox.close_jobs()
            # Files under /outputs become downloadable artifacts, also when the Run failed or was cancelled.
            await run_db(register_outputs, factory, context, sandbox)
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        if model:
            with suppress(Exception):
                await model.close()
    if monitor_error:
        outcome = RuntimeOutcome('interrupted', monitor_error)
    await run_db(store.finish, outcome)
    await run_db(store.stream_finish)
