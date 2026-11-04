from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class InboundMessage:
    channel: str
    external_user_id: str
    conversation_id: str
    text: str

class ChannelConnector(Protocol):
    async def send(self, conversation_id: str, text: str) -> None: ...
