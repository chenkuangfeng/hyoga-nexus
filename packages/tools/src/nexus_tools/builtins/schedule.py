"""Scheduling tools (openspec 2026-11-07-tool-expansion, section 8.2), group `schedule`.

`cronjob_list` only reads. `cronjob_manage` creates, pauses, resumes and deletes the caller's own scheduled tasks;
it always asks for approval, because a scheduled task keeps acting after the conversation is over. The service
behind it (`services.schedule`) enforces ownership, limits and prompt screening; these definitions only carry
requests. A scheduled run is unattended: it cannot ask the user or get approvals, so it only uses what needs neither.
"""
from __future__ import annotations

import json

from nexus_core.runtime import ToolDefinition, ToolResult
from nexus_tools.registry import RegisteredTool
from .services import store_of


def _service(context):
    return getattr(store_of(context), 'schedule', None)


def _failure(error) -> ToolResult:
    code = getattr(error, 'code', 'schedule_failed')
    detail = getattr(error, 'detail', '')
    return ToolResult(code + (f': {detail}' if detail else ''), error_code=code)


def schedule_tools():
    """`cronjob_list` and `cronjob_manage`."""
    async def listing(arguments, context):
        service = _service(context)
        if service is None:
            return ToolResult('schedule_unavailable: scheduling is not available for this Run', error_code='schedule_unavailable')
        jobs = await service.list()
        return ToolResult(json.dumps(jobs, ensure_ascii=False, indent=1) if jobs else 'no scheduled tasks')

    async def manage(arguments, context):
        service = _service(context)
        if service is None:
            return ToolResult('schedule_unavailable: scheduling is not available for this Run', error_code='schedule_unavailable')
        action = arguments['action']
        try:
            if action == 'create':
                missing = [key for key in ('name', 'prompt', 'schedule') if not arguments.get(key)]
                if missing:
                    return ToolResult('schedule_invalid: create needs ' + ', '.join(missing), error_code='schedule_invalid')
                job = await service.create(arguments['name'], arguments['prompt'], arguments['schedule'],
                                           arguments.get('timezone') or 'UTC')
            else:
                if not arguments.get('id'):
                    return ToolResult('schedule_invalid: this action needs the task id from cronjob_list', error_code='schedule_invalid')
                job = await service.change(arguments['id'], action)
        except Exception as error:  # ScheduleError and PlatformError carry stable codes; anything else is generic
            if getattr(error, 'code', None):
                return _failure(error)
            raise
        return ToolResult(json.dumps(job, ensure_ascii=False, indent=1))

    read = lambda r: r.data  # noqa: E731
    yield RegisteredTool(ToolDefinition('cronjob_list', 'List your scheduled tasks with their schedule, state and next run.',
        {'type': 'object', 'properties': {}, 'additionalProperties': False},
        read_only=True, idempotent=True, risk='read'), listing, read)
    yield RegisteredTool(ToolDefinition('cronjob_manage',
        'Create, pause, resume or delete a scheduled task. A task runs the prompt as you, unattended, on this agent '
        'version, in its own conversation; it cannot ask questions or get approvals. Schedules: '
        '{"kind":"interval","every_minutes":N>=15}, {"kind":"daily","at":"09:30"}, {"kind":"weekly","weekday":0-6,"at":"09:30"}.',
        {'type': 'object', 'properties': {
            'action': {'type': 'string', 'enum': ['create', 'pause', 'resume', 'delete']},
            'id': {'type': 'string', 'maxLength': 36},
            'name': {'type': 'string', 'maxLength': 120},
            'prompt': {'type': 'string', 'maxLength': 4000, 'description': 'What to do each time, written so it needs no further input.'},
            'schedule': {'type': 'object'},
            'timezone': {'type': 'string', 'maxLength': 64, 'description': 'IANA name, for example Asia/Shanghai.'}},
         'required': ['action'], 'additionalProperties': False},
        side_effects=True, risk='write', requires_approval=True), manage, read)
