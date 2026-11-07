"""Bounded capture of a command stream: the head and the tail are kept, the middle is dropped."""
from __future__ import annotations

import asyncio

_CHUNK = 65_536


class Sink:
    """Collects one stream up to `limit` bytes, split between its start and its end.

    The end of command output usually holds the result or the error, so a plain prefix would lose it
    (same reasoning as `nexus_tools.output.truncate`). Partial output survives a timeout because the
    sink is owned by the caller, not by the reading task.
    """

    def __init__(self, limit: int):
        self.head_limit = max(1, limit * 7 // 10)
        self.tail_limit = max(1, limit - self.head_limit)
        self.head, self.tail = bytearray(), bytearray()
        self.dropped = 0

    async def drain(self, stream: asyncio.StreamReader) -> None:
        while True:
            chunk = await stream.read(_CHUNK)
            if not chunk:
                return
            room = self.head_limit - len(self.head)
            if room > 0:
                self.head.extend(chunk[:room])
                chunk = chunk[room:]
            if chunk:
                self.tail.extend(chunk)
                overflow = len(self.tail) - self.tail_limit
                if overflow > 0:
                    del self.tail[:overflow]
                    self.dropped += overflow

    @property
    def truncated(self) -> bool:
        return self.dropped > 0

    def text(self) -> str:
        head = bytes(self.head).decode('utf-8', 'replace')
        if not self.dropped:
            return head + bytes(self.tail).decode('utf-8', 'replace')
        return head + f'\n[... 已省略 {self.dropped} 字节 ...]\n' + bytes(self.tail).decode('utf-8', 'replace')
