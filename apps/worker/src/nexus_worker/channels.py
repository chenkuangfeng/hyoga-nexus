"""IM channel connections and replies in the worker (openspec 2026-11-11-enterprise-saas E4, design 7.3).

- :func:`delivery_tick` (idle-time job): send the replies owed for Runs that stopped. Only an explicit retryable
  failure (network trouble) is tried again, up to three attempts; refusals mark the delivery failed.
- :func:`wechat_poller` (task on the Run loop): hold the long-poll of every active WeChat channel this worker leased.
  A lease lasts 90 seconds and is renewed before every poll, so a channel is polled by one worker at a time; losing
  the lease, or the channel no longer being usable, stops its poll. An expired iLink token marks the channel
  ``expired`` so the owner scans again.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from functools import partial

from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)
LEASE_SECONDS = 90
CLAIM_INTERVAL = 10.0
MAX_WECHAT_CHANNELS = 50


def _ilink_client(credentials: dict):
    from nexus_connectors.wechat.ilink import ILinkClient
    return ILinkClient(credentials.get('bot_token') or '', credentials.get('base_url'))


_WECOM = None


def _wecom_api():
    global _WECOM
    if _WECOM is None:
        from nexus_connectors.wecom.client import HttpWeComApi
        _WECOM = HttpWeComApi()
    return _WECOM


def _send(factory, reply, *, wecom=None, ilink=None) -> None:
    from nexus_platform.channels import service
    from nexus_platform.persistence.models import AgentChannelRecord
    with factory() as db, db.begin():
        if reply.kind == 'wecom_app':
            target = service.wecom_app_target(db, reply.channel_id)
        elif reply.kind == 'wechat':
            credentials = service.channel_config(db.get(AgentChannelRecord, reply.channel_id))
        else:
            raise ValueError(f'no sender for {reply.kind}')
    if reply.kind == 'wecom_app':
        (wecom or _wecom_api()).send_text(*target, reply.recipient, reply.text)
    else:
        client = (ilink or _ilink_client)(credentials)
        asyncio.run(client.send_text(reply.recipient, reply.text, reply.reply_context or ''))


def delivery_tick(factory: sessionmaker[Session], *, wecom=None, ilink=None) -> bool:
    """Send pending replies; True when any was attempted."""
    from nexus_platform.channels import service
    from nexus_platform.wecom.client import WeComError
    try:
        from nexus_connectors.wechat.ilink import ILinkError
    except ImportError:  # pragma: no cover
        ILinkError = RuntimeError
    with factory() as db, db.begin():
        replies = service.pending_replies(db)
    for reply in replies:
        sent, retry, error = False, False, ''
        try:
            _send(factory, reply, wecom=wecom, ilink=ilink)
            sent = True
        except WeComError as exc:
            retry, error = exc.code == 'unavailable', str(exc)
        except ILinkError as exc:
            retry, error = exc.retry, str(exc)
        except Exception as exc:  # unexpected: do not loop on it
            error = type(exc).__name__
            logger.warning('Channel reply failed', extra={'run_id': str(reply.run_id)}, exc_info=True)
        with factory() as db, db.begin():
            service.mark_delivery(db, reply.run_id, sent=sent, error=error, retry=retry)
    return bool(replies)


def _sync(factory, fn, *args, **kwargs):
    with factory() as db, db.begin():
        return fn(db, *args, **kwargs)


def _inbound(factory, channel_id, message: dict, message_id: str):
    from nexus_platform.channels import service
    with factory() as db:
        return service.process_inbound(db, channel_id, sender=message['from'], conversation=message['from'],
                                       text=message['text'], message_id=message_id,
                                       reply_context=message['context_token'])


async def _poll_wechat(factory, channel_id, owner: str, stopped: threading.Event, ilink) -> None:
    from nexus_platform.channels import service
    from nexus_platform.persistence.models import AgentChannelRecord
    from nexus_connectors.wechat.ilink import ILinkError
    loop = asyncio.get_running_loop()

    def state(db):
        row = db.get(AgentChannelRecord, channel_id)
        return service.channel_config(row), row.cursor or '', row.tenant_id

    while not stopped.is_set():
        held = await loop.run_in_executor(None, partial(_sync, factory, service.renew_lease, channel_id, owner,
                                                        lease_seconds=LEASE_SECONDS))
        if not held:
            return
        credentials, cursor, _ = await loop.run_in_executor(None, _sync, factory, state)
        client = (ilink or _ilink_client)(credentials)
        try:
            messages, cursor = await client.get_updates(cursor)
        except ILinkError as exc:
            if exc.expired:
                def expire(db):
                    row = db.get(AgentChannelRecord, channel_id)
                    row.status, row.lease_owner, row.lease_until = 'expired', None, None
                await loop.run_in_executor(None, _sync, factory, expire)
                return
            await asyncio.sleep(5)
            continue
        for message in messages:
            message_id = message['id'] or hashlib.sha256(
                f"{message['from']}:{message['text']}:{message['context_token']}".encode()).hexdigest()[:40]
            result = await loop.run_in_executor(None, _inbound, factory, channel_id, message, message_id)
            if result.reply:
                try:
                    await client.send_text(message['from'], result.reply, message['context_token'])
                except ILinkError:
                    logger.warning('WeChat refusal not delivered', extra={'channel_id': str(channel_id)})

        def save(db, value=cursor):
            db.get(AgentChannelRecord, channel_id).cursor = value
        await loop.run_in_executor(None, _sync, factory, save)


async def wechat_poller(factory, stopped: threading.Event, worker_id: str, *, ilink=None,
                        claim_interval: float = CLAIM_INTERVAL) -> None:
    """Claim WeChat channels and keep one poll task per leased channel until the worker stops."""
    from nexus_platform.channels import service
    loop = asyncio.get_running_loop()
    tasks: dict = {}
    try:
        while not stopped.is_set():
            try:
                claimed = await loop.run_in_executor(None, partial(
                    _sync, factory, service.claim_channels, 'wechat', worker_id, lease_seconds=LEASE_SECONDS,
                    limit=MAX_WECHAT_CHANNELS - len(tasks)))
            except Exception:
                logger.warning('Claiming WeChat channels failed', exc_info=True)
                claimed = []
            for channel_id in claimed:
                if channel_id not in tasks or tasks[channel_id].done():
                    tasks[channel_id] = asyncio.create_task(_poll_wechat(factory, channel_id, worker_id, stopped, ilink))
            for channel_id in [key for key, task in tasks.items() if task.done()]:
                tasks.pop(channel_id)
            await asyncio.sleep(claim_interval)
    finally:
        for task in tasks.values():
            task.cancel()
