"""Protocol selection for explicit model-version settings; no platform or credential imports."""
from nexus_core.runtime import RuntimeFault
from .openai_compatible import OpenAICompatibleModel
from .protocols.structured import StructuredModel
from .network import provider_client
from .tool_protocol import TextToolModel

PROTOCOLS = ('openai_chat_completions', 'openai_responses', 'anthropic_messages')


def create_model(*, model: str, api_key: str, options: dict, timeout=60, share_connections: bool = False):
    """Create one authorized model adapter; callers own resolution and must close the result."""
    protocol = options.get('protocol')
    if protocol not in PROTOCOLS:
        raise RuntimeFault('runtime_not_configured')
    base_url = options.get('base_url', 'https://api.anthropic.com/v1' if protocol == 'anthropic_messages' else 'https://api.openai.com/v1')
    client = provider_client(base_url, timeout=timeout, share_connections=share_connections)
    if protocol == 'openai_chat_completions':
        adapter = OpenAICompatibleModel(model=model, api_key=api_key, base_url=base_url, timeout=timeout,
                                       http_client=client, options=options)
    else:
        adapter = StructuredModel(model=model, api_key=api_key, base_url=base_url, protocol=protocol,
                                  http_client=client, options=options)
    return TextToolModel(adapter) if options.get('text_tools') else adapter
