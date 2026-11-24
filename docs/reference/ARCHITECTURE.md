# MCP Server for IFS Cloud - Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│        MCP host (AI agent) - Claude Code, Codex CLI, others            │
│   Same server every time; hosts differ only in how they launch it -    │
│   .claude-plugin/+.mcp.json  /  codex mcp add … python launch.py       │
│                     (Communicates via JSON-RPC/stdio)                   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 │ JSON-RPC over stdio
                                 │
┌────────────────────────────────▼────────────────────────────────────────┐
│                    MCP Server (ifs_mcp/__main__.py)                     │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                     Initialization Layer                          │  │
│  │  • Load .env from the project root (python-dotenv)                │  │
│  │  • Initialize OAuthManager                                        │  │
│  │  • Load saved sessions from disk                                  │  │
│  │  • Start MCP Server (stdio transport)                             │  │
│  │  (OAuth Callback Server starts later, on-demand - see below)      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                    │                                    │
                    │                                    │
        ┌───────────▼────────────┐          ┌────────────▼──────────────┐
        │  OAuth Callback Server │          │   MCP Server Component    │
        │ (http.server on :3000) │          │      (stdio_server)       │
        └────────────────────────┘          └───────────────────────────┘
                    │                                    │
                    │                        ┌───────────▼───────────────┐
                    │                        │     Request Handlers      │
                    │                        │  • ListTools / CallTool   │
                    │                        │  • ListResources / Read   │
                    │                        │  • ListPrompts / GetPrompt│
                    │                        │  • Server instructions    │
                    │                        └───────────┬───────────────┘
                    │                                    │
                    │                        ┌───────────▼───────────────┐
                    │                        │  Tool Registry            │
                    │                        │  ┌─────────────────────┐  │
                    │                        │  │  add_ifs_environment│  │
                    │                        │  │  list_ifs_environ.  │  │
                    │                        │  │  use_ifs_environment│  │
                    │                        │  │  remove_ifs_environ.│  │
                    │                        │  │  start_oauth        │  │
                    │                        │  │  get_session_info   │  │
                    │                        │  │  call_protected_api │  │
                    │                        │  │  get_api_guide      │  │
                    │                        │  │  export_api_data    │  │
                    │                        │  │  import_skill       │  │
                    │                        │  │  save_skill         │  │
                    │                        │  │  parse_har_file     │  │
                    │                        │  │  read_openapi_file  │  │
                    │                        │  └─────────────────────┘  │
                    │                        │                           │
                    │                        │  Prompt Registry          │
                    │                        │  ┌─────────────────────┐  │
                    │                        │  │  build_from_proj.   │  │
                    │                        │  │  build_from_har     │  │
                    │                        │  │  build_from_openapi │  │
                    │                        │  └─────────────────────┘  │
                    │                        │                           │
                    │                        │  Resource Registry        │
                    │                        │  ┌─────────────────────┐  │
                    │                        │  │  auto-discovered    │  │
                    │                        │  │  SKILLS_DIR/ (opt.) │  │
                    │                        │  │  ifs_mcp/resources/ │  │
                    │                        │  │  *.md (hot-reload)  │  │
                    │                        │  └─────────────────────┘  │
                    │                        └───────────┬───────────────┘
                    │                                    │
                    │                                    │
        ┌───────────▼────────────────────────────────────▼───────────────┐
        │                    Authentication Layer                        │
        │  ┌──────────────────────────────────────────────────────────┐  │
        │  │                OAuthManager (auth/oauth.py)              │  │
        │  │  • start_auth_flow() - Generate PKCE & auth URL          │  │
        │  │  • exchange_code() - Trade code for tokens               │  │
        │  │  • refresh_access_token() - Refresh expired tokens       │  │
        │  │  • client_credentials_token() - Headless machine-to-mach.│  │
        │  │  • get_access_token() - Get valid token (auto-refresh)   │  │
        │  └──────────────────────────────────────────────────────────┘  │
        │                                                                │
        │  ┌──────────────────────────────────────────────────────────┐  │
        │  │             Sessions (auth/sessions.py)                  │  │
        │  │  • load_sessions() - Load ~/.ifs-mcp/session.json        │  │
        │  │  • save_session() / remove_session() - Persist or delete │  │
        │  │  • get_current_session_id() - Active environment's key   │  │
        │  │    (delegates to get_active_session_key() in config.py)  │  │
        │  │  • initialize_token_store() - Restore sessions on start  │  │
        │  └──────────────────────────────────────────────────────────┘  │
        │                                                                │
        │  ┌──────────────────────────────────────────────────────────┐  │
        │  │            Token Store (auth/sessions.py)                │  │
        │  │  • In-memory dict[session key, token record] + lock      │  │
        │  │  • Stores: accessToken, refreshToken, expiresAt,         │  │
        │  │    issuedAt, userId                                        │  │
        │  └──────────────────────────────────────────────────────────┘  │
        └────────────────────────────────────────────────────────────────┘
                    │                                    │
                    │                                    │
        ┌───────────▼────────────┐           ┌───────────▼───────────────┐
        │  OAuth Provider        │           │   Protected API Server    │
        │  (IFS Cloud/Keycloak)  │           │   (IFS Cloud REST API)    │
        │  • Authorization       │           │   • Business endpoints    │
        │  • Token Exchange      │           │   • Requires Bearer token │
        │  • Token Refresh       │           │                           │
        └────────────────────────┘           └───────────────────────────┘
```

## Components

### 1. Entry Point (`src/ifs_mcp/__main__.py`, `launch.py`)
Application bootstrap: loads `.env` from the project root, initializes OAuthManager, restores saved sessions, starts the MCP (stdio) server. `launch.py` is what hosts run: it re-launches itself under the repo's `.venv` when one exists. The OAuth callback server is **not** started here - it only starts on-demand when `start_oauth` is called.

### 2. MCP Server (`src/ifs_mcp/server.py`)
MCP protocol handler, built on the `mcp` SDK's low-level `Server` (not FastMCP, because guides must be rescanned on every request). Registers tool, resource, and prompt definitions. Routes tool calls to handlers, serves resource content on read requests, and executes prompt handlers that return structured conversation messages.

### 3. OAuth Callback Server (`src/ifs_mcp/auth/callback_server.py`)
Standard-library `http.server` on a background thread, bound to `127.0.0.1:3000` (loopback only, so nothing else on the network can reach it). Started **on-demand** by the `start_oauth` tool (not at process boot) - not running at any other time. Handles `/oauth/callback` redirects, exchanges auth codes for tokens, saves sessions to disk. Never used at all for `client_credentials` environments, which authenticate without a browser.

### 4. API Client (`src/ifs_mcp/api_client.py`)
Authenticated HTTP client (`httpx`). Resolves the base URL per-environment via `get_api_base_url_for_key()` (falls back to the legacy flat `API_BASE_URL` env var), attaches Bearer token, used by all tools. Exports `ALLOWED_REQUEST_HEADERS`/`disallowed_headers()` - the allowlist tool handlers validate caller-supplied headers against (`If-Match`, `If-None-Match`, `X-IFS-Content-Disposition`). `build_api_url()` joins the environment's base URL and the model-supplied endpoint and returns nothing unless the endpoint is a plain path starting with a single `/` and the result keeps the base URL's origin, so a crafted endpoint (`@evil.com/x`, `//evil.com`) can never redirect the bearer token to another host. `call_protected_api()` also enforces `readOnly` on the environment the request is actually sent to (the resolved session key), so every tool and every `sessionId`/`environment` argument is covered. Server headers are set last on a case-insensitive `httpx.Headers`, so caller headers can never override `Authorization`/`Accept`/`Content-Type` even if a tool's own validation were bypassed. Redirects are not followed, so the token is never sent anywhere else - defense in depth, not the primary guard.

### 5. Authentication Layer

**OAuth Manager** (`src/ifs_mcp/auth/oauth.py`) - OAuth 2.0 + PKCE flow orchestration for `authorization_code` environments, plus `client_credentials_token()` for machine-to-machine auth on `client_credentials` environments. Automatic token refresh/re-fetch via `refresh_margin_ms()`, scaled to each token's own lifetime (10%, floored at 5s, capped at 30s) rather than a fixed buffer - a fixed 5-minute buffer meant any environment issuing shorter-lived tokens (some `client_credentials` setups do) would re-fetch a token before every single API call. Sessions persisted before this existed have no `issuedAt` and fall back to the old fixed 5-minute buffer once, then pick up the scaled margin on their next renewal.

**Sessions** (`src/ifs_mcp/auth/sessions.py`) - Persists sessions to `~/.ifs-mcp/session.json`, keyed per environment, in the same camelCase / epoch-millisecond layout as the TypeScript version; restores on startup. Also holds the in-memory token store, guarded by a lock because the callback thread writes to it.

### 6. Configuration (`src/ifs_mcp/endpoints.py`, `src/ifs_mcp/config.py`)
Two resolution paths, checked in this order:
1. **Environment variables** (legacy, always wins if set): `API_BASE_URL`, `OAUTH_REALM`, `OAUTH_CLIENT_ID`, `SKILLS_DIR`, `EXPORT_DIR` (also read from a `.env` file in the project root).
2. **Environment registry** (`src/ifs_mcp/config.py`, persisted to `~/.ifs-mcp/config.json`): named environments, each with its own `apiBaseUrl`/`oauthRealm`/`oauthClientId`, optional `authMode` (`authorization_code` default, or `client_credentials`), and `readOnly` flag. A client secret is not part of the registry the tools see: it comes from the `IFS_CLIENT_SECRET_<NAME>` environment variable or a `clientSecret` entry added to `config.json` by hand, and only `get_client_secret()` reads it. This is the main configuration path for every host. See [Managing IFS Environments](../getting-started/ENVIRONMENTS.md).

Session/token keys are the active environment's name (or `"default"` in legacy env-var mode) rather than an opaque generated ID - `get_active_session_key()` in `config.py` resolves this, so tokens are always paired with the environment they were issued for.

### 7. Tools

| Tool | Category | Description |
|------|----------|-------------|
| `add_ifs_environment` | Environment | Register (or update) a named IFS environment, auth mode, and optional read-only flag |
| `list_ifs_environments` | Environment | List registered environments, which is active, and auth status |
| `use_ifs_environment` | Environment | Switch which environment subsequent calls target |
| `remove_ifs_environment` | Environment | Delete an environment and its saved session |
| `start_oauth` | Auth | Initiate OAuth flow (browser for `authorization_code`; silent token fetch for `client_credentials`) |
| `get_session_info` | Auth | Check session status for the active environment |
| `call_protected_api` | API | Generic authenticated API calls; accepts an optional `environment` override and an allowlisted `headers` map (`If-Match`, `If-None-Match`, `X-IFS-Content-Disposition`). Blocks non-GET methods on `readOnly` environments (enforced in the shared API client, so `export_api_data` is covered too), rejects endpoints that are not a path on the configured host, refuses to guess when several environments exist and none is selected, and replaces responses over 100 KB with a summary plus one sample record |
| `get_api_guide` | API | Find and return a skill (API guide). Matches keywords against each guide's name, URI and description, lists close runner-ups, and when nothing matches returns instructions to find the projection through the client navigator and confirm with the user before building a new skill |
| `export_api_data` | API | Export large result sets to CSV with automatic pagination; keyed/singleton endpoints export as one row with no pagination |
| `import_skill` | Skills | Import a skill `.md` from a URL or local file path |
| `save_skill` | Skills | Save or update a skill `.md`; returns a change diff for updates |
| `parse_har_file` | Skill authoring | Parse a browser HAR file; returns structured summary of IFS API operations |
| `read_openapi_file` | Skill authoring | Parse a downloaded OpenAPI/Swagger JSON file; returns entity sets and field schemas |

### 8. Prompts

MCP prompts are guided conversation starters. Claude Code lists them as slash commands (type `/` and look for the `build_ifs_skill_from_*` entries); Codex CLI has no prompt surface for them. They accept arguments and return structured messages that set up a specific workflow.

| Prompt | Arguments | Description |
|--------|-----------|-------------|
| `build_ifs_skill_from_projection` | `projection_name`, `skill_name` | Fetch the OpenAPI spec live from IFS and build a skill |
| `build_ifs_skill_from_har` | `har_file_path`, `skill_name` | Build a skill from a browser HAR recording |
| `build_ifs_skill_from_openapi` | `openapi_file_path`, `skill_name` | Build a skill from a downloaded OpenAPI/Swagger JSON file |

Each prompt accepts `skill_name` (the output filename without `.md`) alongside its primary input. All three paths call `get_api_guide("ifs-skill-authoring")` to load format instructions, then invoke their respective parser tool (`parse_har_file` / `read_openapi_file` / live API fetch), and converge into the same guided Q&A and `save_skill` completion flow.

### 9. Resources

MCP resources provide API guides as markdown that Claude reads to learn how to construct `call_protected_api` calls for specific IFS projections.

| Resource | URI | Description |
|----------|-----|-------------|
| IFS OData Reference | `ifs://ifs-common-odata-reference/guide` | OData query syntax reference for IFS Cloud projections |
| IFS Framework Client Navigator | `ifs://ifs-framework-client-navigator/guide` | Finds the projection behind an IFS screen from its navigator label |
| IFS Framework Quick Reports | `ifs://ifs-framework-quick-reports/guide` | Searches, inspects and runs Quick Reports |
| IFS Skill Authoring Guide | `ifs://ifs-skill-authoring/guide` | Format reference the `build_ifs_skill_*` prompts load via `get_api_guide("ifs-skill-authoring")` |

Resources are scanned fresh on every request (`get_guides()` called per `ListResources` / `ReadResource` / `get_api_guide`). Two directories are scanned, in this order: `SKILLS_DIR` (if set) and the package's `resources/` folder (where the bundled guides live). When two files share a name, the first one found wins, so a skill in `SKILLS_DIR` overrides a bundled one. Adding, updating, or removing a `.md` file takes effect immediately - no server restart needed. Metadata is derived from file content: the first `# Heading` becomes the name, the first non-empty line that is not a heading becomes the description, and the filename becomes the URI slug. The description is also what `get_api_guide` matches on, so write it as a one-line summary that says when to use the guide.

## Data Flow

### OAuth Authentication
```
LLM ──start_oauth──> MCP Server ──generate PKCE──> Return authUrl
User opens URL in browser ──> OAuth Provider ──authenticates──> Redirect to localhost:3000
Callback server ──exchange code──> OAuth Provider ──returns tokens──> Save to store & disk
```

### API Call (with Auto-Refresh)
```
LLM ──tool call──> MCP Server ──get active environment's session──> Session Manager
  ──get token──> Token Store ──expired?──> authorization_code: refresh with OAuth Provider
                              ──expired?──> client_credentials: re-fetch (no refresh token issued)
  ──valid token──> httpx ──Bearer auth──> IFS Cloud API ──response──> LLM
```

### What reaches the AI model
The server returns tool results to the MCP host, and the host sends the conversation to its AI model provider. See the [FAQ](../FAQ.md#data-flow-and-privacy) for what each tool returns and what stays local.

### Skill Authoring (Capture → Refine → Make → Use)
```
HAR path (build_ifs_skill_from_har):
1. CAPTURE
   User works in IFS Cloud browser UI
   DevTools Network tab ──export──> .har file

2. REFINE
   User invokes build_ifs_skill_from_har(har_file_path=..., skill_name=...)
   Claude calls parse_har_file tool ──parse_har()──> filtered operation groups
   Claude presents summary ──asks clarifying questions──> User answers

OpenAPI path - local file (build_ifs_skill_from_openapi):
1. DOWNLOAD
   User fetches {server}/.svc/$openapi?V2 from browser, saves as JSON

2. REFINE
   User invokes build_ifs_skill_from_openapi(openapi_file_path=..., skill_name=...)
   Claude calls read_openapi_file tool ──parse_openapi()──> entity sets + field schemas
   Claude presents summary ──asks clarifying questions──> User answers

OpenAPI path - live fetch (build_ifs_skill_from_projection):
1. REFINE (directly)
   User invokes build_ifs_skill_from_projection(projection_name=CustomerHandling, skill_name=...)
   Claude calls call_protected_api ──$openapi?V2──> spec JSON
   Claude extracts entity sets, fields ──asks clarifying questions──> User answers

All paths converge:
3. MAKE
   Claude drafts .md guide ──calls save_skill(filename=skill_name, content=...)──>
   save_skill writes to SKILLS_DIR/ (if set) or src/ifs_mcp/resources/
   (update path: reads old file ──diff──> returns change summary)

4. USE
   Next get_api_guide call ──get_guides() scans dir──> skill available immediately
   No restart needed
   Share: copy .md URL ──recipient runs──> import_skill({ source: url })
```

## Design Decisions

1. **Dual Server Architecture** - `http.server` thread for browser OAuth callbacks (started on-demand, not at boot) + MCP stdio for the client, whichever it is. Both in one process when the callback server is running.
2. **Session Persistence** - Sessions survive restarts via `~/.ifs-mcp/session.json`, keyed per environment. LLM doesn't need to track session IDs. Refreshed tokens are also persisted so sessions continue seamlessly after restarts.
3. **Automatic Token Refresh** - Transparent to LLM. Lifetime-scaled margin in `getAccessToken()` (`refreshMarginMs()`) - not a fixed buffer, so short-lived tokens aren't re-fetched before every call.
4. **Modular Tool Design** - Each tool is a `(definition, handler)` pair; the definition is the same JSON the TypeScript version used. Registered in `tools/__init__.py`.
5. **Resource-Driven API Knowledge** - Instead of hardcoding tools per endpoint, API guides (markdown) teach the LLM how to use `call_protected_api`. Users can add new guides without code changes.
6. **Three Skill Authoring Paths** - HAR-based authoring captures real browser traffic (what users actually do). OpenAPI-based authoring uses the projection's `$openapi?V2` spec (full CRUD surface with typed field schemas) - either live-fetched or from a local file. HAR is better for transactional workflows; OpenAPI is better for master data. All three paths converge into the same guided Q&A and `save_skill` flow. `skill_name` is provided upfront so Claude saves with the correct filename without asking.
7. **Portable Skills** - Skill files are plain markdown. Export = share the file. Import = `import_skill` tool. No registry or special format needed.
8. **Security** - Default (`authorization_code`) mode uses a public OAuth client with PKCE - no client secret involved. `client_credentials` mode is the exception: it requires a confidential client whose secret you supply yourself (environment variable or `config.json`). The secret is never accepted through chat, is read in one place (`OAuthManager.client_credentials_token()`), and a test (`tests/test_config_and_auth.py`) enforces that in CI (see [Security](../../SECURITY.md#if-you-use-client_credentials-environments)). Plus: CSRF state parameter, HTTPS-only remote skill imports, path traversal protection on skill writes, tokens stored locally.
9. **Host-Agnostic Core** - Nothing under `src/` reads `.claude-plugin/`. Each host's config only declares how to launch the same `launch.py` - the server itself never knows or cares which host started it. Codex CLI needs no packaging at all - a direct `codex mcp add` / `config.toml` entry works unmodified, since MCP is a protocol, not a client-specific integration.
10. **Guided Skill Lookup** - `get_api_guide` scores guides by keyword against name, URI and description and returns the best match (listing close runner-ups). The server's MCP `instructions` tell the model to load a guide before any API call and to resolve a screen name to a projection with the `ifs-framework-client-navigator` guide. When no guide matches, the result tells the model to search the navigator, show the hits, and ask before building a skill (always asking which one when there are several). The scoring and the instruction text live in the server; the navigator query and the confirmation are driven by the model through `call_protected_api`, so the existing authentication and environment handling applies.

## File Structure
```
launch.py                             # What hosts run; re-launches under .venv when present
pyproject.toml                        # Package metadata, dependencies, ruff/pytest config
src/ifs_mcp/
├── __main__.py                       # Entry point (python -m ifs_mcp / ifs-mcp)
├── server.py                         # MCP handlers and server instructions
├── config.py                         # Environment registry (~/.ifs-mcp/config.json)
├── endpoints.py                      # Base URL / OAuth endpoints per environment
├── api_client.py                     # Authenticated HTTP client + guards
├── resources.py                      # Guide discovery (SKILLS_DIR, bundled)
├── prompts.py                        # 3 skill-building prompts (projection / HAR / OpenAPI)
├── util.py                           # JSON output helpers
├── ui.py, logo.png                   # Browser login + result pages (self-contained HTML)
├── auth/
│   ├── oauth.py                      # OAuth flow logic (authorization_code + client_credentials)
│   ├── sessions.py                   # Session persistence + in-memory token store
│   └── callback_server.py            # OAuth callback (started on-demand)
├── parsers/
│   ├── har.py                        # HAR parsing (parse_har, summarise_har)
│   └── openapi.py                    # OpenAPI/Swagger parsing (parse_openapi, summarise_openapi)
├── resources/                        # Bundled guides (*.md)
└── tools/
    ├── __init__.py                   # Tool registry
    ├── env.py                        # add / list / use / remove_ifs_environment
    ├── auth.py                       # start_oauth, get_session_info
    ├── api.py                        # call_protected_api, get_api_guide, export_api_data
    └── skills.py                     # save_skill, import_skill, parse_har_file, read_openapi_file
tests/                                # pytest suite
```

## Build and Release

There is no build step: the package is installed editable into `.venv` (`pip install -e .`), and hosts run `launch.py`. CI (`.github/workflows/ci.yml`) runs `ruff` and `pytest` on Python 3.10 and 3.13, on Ubuntu and Windows. The tests include the checks the TypeScript version ran as scripts: only `auth/oauth.py` reads a client secret, and the package, `pyproject.toml` and plugin versions match.

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp` | MCP protocol implementation (official Python SDK) |
| `httpx` | HTTP client for API, token and skill-import calls |
| `python-dotenv` | `.env` loading |
| standard library | `http.server` (OAuth callback), `hashlib`/`secrets` (PKCE) |
