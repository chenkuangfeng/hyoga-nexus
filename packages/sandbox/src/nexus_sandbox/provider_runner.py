"""Standalone instance runner. Captures output with bounded memory before the provider SDK sees it."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import resource
import sys
import pwd
import shutil
import time
from pathlib import Path

# Uploaded alongside this module. No Nexus installation is required inside a provider template.
from nexus_output import Sink, feed_stdin
from nexus_transfer import pack, unpack


def prepare(base: Path) -> None:
    """Prepare virtual roots as root, then assign only workspace and outputs to the execution user."""
    request = json.loads((base / 'request.json').read_text())
    staging = base / 'stage'
    staging.mkdir()
    unpack(base / 'input.tar', staging, roots=('workspace', 'outputs', 'skills'),
           limit=request['transfer_limit'])
    user = pwd.getpwnam('user')
    for name in ('workspace', 'outputs', 'skills'):
        target = Path('/') / name
        if target.is_mount():
            raise ValueError('provider virtual roots must not contain pre-mounted volumes')
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        shutil.move(str(staging / name), target)
        readonly = name == 'skills'
        uid, gid = (0, 0) if readonly else (user.pw_uid, user.pw_gid)
        for directory, _, files in os.walk(target):
            os.chown(directory, uid, gid)
            os.chmod(directory, 0o555 if readonly else 0o755)
            for filename in files:
                path = Path(directory) / filename
                os.chown(path, uid, gid)
                if readonly:
                    path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
    os.chown(base, user.pw_uid, user.pw_gid)


async def run(base: Path) -> None:
    request = json.loads((base / 'request.json').read_text())
    limit = request['transfer_limit']
    # Files run under the same unprivileged account as this helper. Skill protection is supplied by
    # the platform's template policy and checked by acceptance, not inferred from a directory name.
    started = time.monotonic()
    limits = request.get('limits')
    if limits:
        # One VM belongs to one request, so this UID-wide kernel limit covers this command tree.
        resource.setrlimit(resource.RLIMIT_NPROC, (int(limits['pids']), int(limits['pids'])))
    process = await asyncio.create_subprocess_exec(
        '/bin/sh', '-c', request['command'], cwd=request['cwd'],
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/workspace', 'LANG': 'C.UTF-8',
             **(request['env'] or {})}, start_new_session=True,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = Sink(request['output_limit']), Sink(request['output_limit'])
    readers = [asyncio.create_task(out.drain(process.stdout)), asyncio.create_task(err.drain(process.stderr))]
    writer = asyncio.create_task(feed_stdin(process, request['stdin']))
    current = asyncio.current_task()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        asyncio.get_running_loop().add_signal_handler(sig, current.cancel)
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), request['timeout_seconds'])
    except (TimeoutError, asyncio.CancelledError) as error:
        timed_out = isinstance(error, TimeoutError)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        try:
            await asyncio.wait_for(asyncio.gather(*readers, writer), 5)
        except TimeoutError:
            pass  # detached writers cannot keep the capture alive past the request deadline
    result = dict(exit_code=None if timed_out else process.returncode, timed_out=timed_out,
                  stdout=out.text(), stderr=err.text(), stdout_truncated=out.truncated,
                  stderr_truncated=err.truncated, duration_ms=int((time.monotonic() - started) * 1000))
    (base / 'result.json').write_text(json.dumps(result))
    pack({root: Path('/') / root for root in ('workspace', 'outputs')}, base / 'output.tar', limit=limit)


if __name__ == '__main__':
    base = Path(sys.argv[1])
    if len(sys.argv) == 3 and sys.argv[2] == 'prepare':
        prepare(base)
    else:
        asyncio.run(run(base))
