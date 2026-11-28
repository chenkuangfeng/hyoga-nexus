"""Compatibility exports for vendor-neutral runtime contracts; implementations live by responsibility."""
from .errors import RuntimeFault
from .cancellation import CancellationTokenPort
from .tools import ConcurrencyHint, ToolCall, ToolDefinition, ToolDisposition, ToolResult, ToolGatewayPort
from .models import ModelMessage, ModelRequest, ModelChunk, ChatModelPort
from .events import LifecycleEvent, RuntimeLifecycleHook
from .budgets import ExecutionBudget, RuntimeProgress
from .store import RuntimeStorePort
from .memory import MemoryDraftPort
from .sandbox import SandboxRequest, SandboxResult, SandboxPort
from .outcomes import RuntimeOutcome
from .context import (ContextDependency, ContextBlock, ContextBuildInput, AssemblyManifest, RunContextSnapshot, ContextProvider)
from .port import AgentRuntime, RunContext, RunRequest, RuntimeCapabilities

__all__ = [
    'ContextDependency', 'ContextBlock', 'ContextBuildInput', 'AssemblyManifest', 'RunContextSnapshot', 'ContextProvider',
    'RuntimeFault',
    'CancellationTokenPort',
    'ToolCall',
    'ConcurrencyHint',
    'ToolDefinition',
    'ToolDisposition',
    'ToolResult',
    'ToolGatewayPort',
    'ModelMessage',
    'ModelRequest',
    'ModelChunk',
    'ChatModelPort',
    'LifecycleEvent',
    'RuntimeLifecycleHook',
    'ExecutionBudget',
    'RuntimeProgress',
    'RuntimeStorePort',
    'MemoryDraftPort',
    'SandboxRequest',
    'SandboxResult',
    'SandboxPort',
    'RuntimeOutcome',
    'AgentRuntime',
    'RunContext',
    'RunRequest',
    'RuntimeCapabilities',
]
