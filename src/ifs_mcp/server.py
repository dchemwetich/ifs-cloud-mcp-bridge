"""MCP server: tools, guide resources and prompts over stdio."""

from __future__ import annotations

from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__
from .auth.oauth import OAuthManager
from .prompts import PROMPTS
from .resources import get_guides
from .tools import TOOLS
from .util import text_result

SERVER_INSTRUCTIONS = (
    "IFS Cloud endpoints, projection names and OData syntax are customer-specific and cannot be guessed. "
    "Before any call_protected_api call, load the matching skill with get_api_guide (call it with no argument to list guides). "
    "To find which projection a screen, page or menu entry uses, load the 'ifs-framework-client-navigator' guide first. "
    "If no guide matches, find the projection through the navigator, show the user the hit(s), and get their confirmation "
    "(always when there are several hits) before building a new skill with the ifs-skill-authoring guide and save_skill. "
    "Never probe or invent endpoints."
)


def build_server(oauth: OAuthManager) -> Server[Any]:
    tool_defs = [types.Tool.model_validate(d) for d, _ in TOOLS]
    handlers = {d["name"]: h for d, h in TOOLS}
    prompt_defs = [types.Prompt.model_validate(d) for d, _ in PROMPTS]
    prompt_handlers = {d["name"]: h for d, h in PROMPTS}

    async def list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tool_defs)

    async def call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        handler = handlers.get(params.name)
        if handler is None:
            raise ValueError(f"Unknown tool: {params.name}")
        try:
            result = await handler(dict(params.arguments or {}), oauth)
        except Exception as exc:  # surface as a tool error rather than dropping the connection
            result = text_result(f"Error: {exc}", is_error=True)
        return types.CallToolResult.model_validate(result)

    # Guides are rescanned on every request so a newly saved skill shows up at once.
    async def list_resources(_ctx: Any, _params: Any) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[types.Resource.model_validate(g.definition()) for g in get_guides()])

    async def read_resource(_ctx: Any, params: types.ReadResourceRequestParams) -> types.ReadResourceResult:
        uri = str(params.uri)
        guide = next((g for g in get_guides() if g.uri == uri), None)
        if guide is None:
            raise ValueError(f"Unknown resource: {uri}")
        return types.ReadResourceResult.model_validate(
            {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": guide.read()}]}
        )

    async def list_prompts(_ctx: Any, _params: Any) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=prompt_defs)

    async def get_prompt(_ctx: Any, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        handler = prompt_handlers.get(params.name)
        if handler is None:
            raise ValueError(f"Unknown prompt: {params.name}")
        return types.GetPromptResult.model_validate(handler(dict(params.arguments or {})))

    return Server(
        "ifs-mcp-server",
        version=__version__,
        instructions=SERVER_INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
    )


async def run(oauth: OAuthManager) -> None:
    server = build_server(oauth)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
