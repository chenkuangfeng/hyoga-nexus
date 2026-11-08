"""MCP client, server and gateway (openspec 2026-11-08-mcp).

`nexus_mcp.client` connects external MCP servers (stdio / streamable HTTP / SSE), discovers tools,
and calls them. `nexus_mcp.gateway` bridges enabled tools into the authorized tool gateway;
`nexus_mcp.server` exposes a Run's authorized tools over MCP with a run token.
"""
