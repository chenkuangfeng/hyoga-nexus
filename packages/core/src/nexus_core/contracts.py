from dataclasses import dataclass
from typing import AsyncIterator, Protocol

@dataclass(frozen=True)
class AgentRequest:
    session_id: str
    prompt: str

@dataclass(frozen=True)
class AgentEvent:
    kind: str
    content: str

class AgentRuntime(Protocol):
    def stream(self, request: AgentRequest) -> AsyncIterator[AgentEvent]: ...

@dataclass(frozen=True)
class InboundMessage:
    channel: str
    external_user_id: str
    conversation_id: str
    text: str

class ChannelConnector(Protocol):
    async def send(self, conversation_id: str, text: str) -> None: ...
