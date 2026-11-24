# Python Port Plan - ifs-cloud-mcp-bridge

Status: **done** (2026-11-14). All six phases complete; v2.0.0 runs on Python.

## Outcome

- **Parity:** the Node and Python servers were run side by side through the same MCP calls
  (a harness comparing every tool, resource and prompt response). Matching: tool list and
  schemas, guides, all 3 prompts, the environment tools, every guard, the skill tools, the
  HAR/OpenAPI summaries, and live GET calls on a test IFS Cloud instance (navigator search, the over-100 KB
  summary, a 404, CSV export byte-identical). Only differences: the wording of OS
  file-not-found errors (`ENOENT …` vs `[Errno 2] …`).
- **Live auth:** browser login (PKCE) and token refresh verified against a test IFS Cloud instance.
- **Tests:** 43 pytest tests covering the 15 rules below, the parsers and version matching.
- **Deliberate differences from the TypeScript version:**
  - Request headers are case-insensitive, so a lowercase `authorization` from a caller can
    no longer be sent alongside the real token (found by the tests).
  - API calls do not follow redirects and time out after 120 s (axios followed redirects,
    with no timeout).
  - Guides are read byte-for-byte (CRLF kept), as Node did.
- **Fixed after the port:** an expired or revoked refresh token (token endpoint 400/401,
  e.g. `invalid_grant`) used to return `API call failed`, so the model did not start a new
  login by itself. It now returns `authentication_required` and removes the dead session;
  a missing session does the same. Token-server outages (5xx, network) still return
  `API call failed` and keep the session, since a retry may work.
- **Changed from rule 9:** only a 401 returns `authentication_required`. A 403 now returns
  `permission_denied` and tells the model not to log in again: the token is valid but the IFS
  user lacks the permission set, so a new login hit the same 403 and the model looped. A 412
  returns `precondition_failed` and tells the model to re-read the record and ask before
  retrying with the new etag (no automatic retry).
- There are 3 prompts (projection, HAR, OpenAPI), not 2 as first written below.

## Goal

Rewrite the TypeScript MCP server (v1.3.0, ~3,400 lines in `src/`) in Python with **the same
behaviour**, so that existing users of it notice nothing except the runtime:

- same 13 tool names, input schemas and result shapes
- same `ifs://<slug>/guide` resources and 2 prompts
- same files on disk: `~/.ifs-mcp/config.json`, `~/.ifs-mcp/session.json` (camelCase keys,
  epoch-millisecond times), skills folder, CSV export location
- same environment variables: `API_BASE_URL`, `OAUTH_REALM`, `OAUTH_CLIENT_ID`, `SKILLS_DIR`,
  `IFS_CLIENT_SECRET_<NAME>`, plus `.env` in the project root
- same server instructions text

Existing skills, registered environments and saved logins keep working without changes.

## Stack

| Concern | TypeScript today | Python |
|---|---|---|
| MCP | `@modelcontextprotocol/sdk` low-level `Server` | `mcp` SDK, low-level `mcp.server.lowlevel.Server` + `stdio_server` |
| HTTP | `axios` | `httpx` |
| OAuth callback | `express` on 127.0.0.1:3000 | stdlib `http.server` on a background thread, 127.0.0.1:3000 |
| Validation | `zod` (via SDK) | JSON schemas copied as-is; `pydantic` comes with `mcp` |
| `.env` | `dotenv` | `python-dotenv` |
| Build | `tsc` | none; `pyproject.toml`, editable install in a venv |
| Tests | none | `pytest` |
| Lint | - | `ruff` |

**Why the low-level `Server` and not `FastMCP`:** guides are rescanned from disk on every
request (hot reload of new skills). FastMCP registers resources once at start-up. The low-level
server also lets the tool JSON schemas be copied over unchanged, which keeps the tools
identical for the model.

Python ≥ 3.10 (the `mcp` SDK minimum). The dev machine has 3.14.

## Layout

The port is built in `python/` beside the TypeScript code until it matches it, then moved
to the repo root at cutover (Phase 6).

```
python/
  pyproject.toml              # name ifs-cloud-mcp-bridge, entry point ifs-mcp = ifs_mcp.__main__:main
  src/ifs_mcp/
    __main__.py               # load .env, init token store, run server     (index.ts)
    server.py                 # handlers, instructions, registry            (server/mcp-server.ts, tools/index.ts)
    config.py                 # environments, secrets                       (lib/config.ts)
    endpoints.py              # base URL / realm / OAuth URLs per env       (lib/types.ts)
    api_client.py             # call + URL/header guards + readOnly         (lib/api-client.ts)
    auth/
      oauth.py                # PKCE, code exchange, refresh, client_credentials (oauth-manager.ts)
      sessions.py             # session.json + in-memory store              (session-manager.ts, token-store.ts)
      callback_server.py      # /oauth/callback                             (server/oauth-callback-server.ts)
    parsers/
      har.py                  # (lib/har-parser.ts)
      openapi.py              # (lib/openapi-parser.ts)
    tools/
      env.py                  # add / list / use / remove_ifs_environment
      auth.py                 # start_oauth (+ login HTML page), get_session_info
      api.py                  # call_protected_api, get_api_guide, export_api_data
      skills.py               # save_skill, import_skill, parse_har_file, read_openapi_file
    resources.py              # guide discovery                             (resources/index.ts)
    prompts.py                # build_ifs_skill_from_projection / _from_har (prompts/*)
    resources/*.md            # the 4 bundled guides, copied unchanged
  tests/
```

## Behaviour that must carry over exactly

These are the safety rules and edge cases in the TypeScript code. Each gets a unit test.

1. **The endpoint can't change the host.** `build_api_url`: the path must start with a
   single `/`, contain no control characters or `\`, and the final URL must keep the
   base URL's origin. This blocks `@evil.com/x` and `//evil.com`.
2. **Header allowlist.** Only `If-Match`, `If-None-Match` and `X-IFS-Content-Disposition`
   are accepted from the model. Server-set `Authorization` / `Accept` / `Content-Type` are
   applied last so they always win.
3. **Read-only is enforced in the API client** against the environment the request actually
   goes to, so a per-call `environment` override can't get round it. Only GET is allowed.
   Export uses the same path.
4. **Client secret:** read only inside the client_credentials token call, from
   `IFS_CLIENT_SECRET_<NAME>` first, then `config.json`. It is never logged, returned or put
   in an error. httpx exceptions carry the request, so errors are rebuilt from status +
   `error_description` only, never `str(exc)`. `list` and `add` report the secret's source
   (`env` / `config` / `missing`), never its value.
5. **Config writes:** `add` keeps a hand-added `clientSecret`, and keeps `readOnly` unless the
   caller sets it explicitly. The first environment added becomes active. Removing the
   active environment picks the only remaining one, otherwise none.
6. **OAuth:** PKCE S256, 32-byte verifier, 16-byte hex state, pending flows expire after
   10 minutes, each flow is bound to the environment active when it started, scope `openid`,
   redirect `http://localhost:3000/oauth/callback`.
7. **Token renewal margin:** 10 % of the token's lifetime, at least 5 s and at most 30 s.
   Sessions without `issuedAt` use 300 s. client_credentials renews by asking again
   (no refresh token).
8. **Callback server:** binds 127.0.0.1 only, starts once, ignores "port already in use",
   and HTML-escapes error text.
9. **401/403 → `authentication_required`**, with the "call start_oauth now" message, so the
   model logs in again automatically.
10. **Responses over 100 KB** are not returned. Instead the model gets the record count, a
    sample record and the options. Same `_instruction` text.
11. **CSV export:** batches of 100 rows using `$top`/`$skip`, `;` as the delimiter, UTF-8 with
    BOM, written to `~/Downloads`, falling back to `~/.ifs-mcp/exports`. A keyed endpoint
    exports one row.
12. **import_skill:** `https://` only, at most 3 redirects. Local file paths are allowed.
13. **Guide discovery:** `SKILLS_DIR` first, then the bundled guides; the first file with a
    given name wins. Name comes from the first `# ` heading; the description from the first
    non-heading line with `` ` * _ `` removed.
14. **Opening the browser:** `os.startfile` / `open` / `xdg-open` with the URL passed as an
    argument, never through a shell string. The login HTML page is written to the temp folder.
15. **Session files** are written with mode 0600 where the OS supports it, and the folder
    with 0700.

## Phases

Each phase ends with the Python server running **side by side** with the TypeScript one in
Claude Code, registered as a second server `ifs-py`
(`claude mcp add ifs-py -- <venv>\Scripts\python.exe -m ifs_mcp`). Each phase's tools are
compared against the TypeScript output on a test instance using **GET calls only**.

| # | Scope | Done when |
|---|---|---|
| 1 | Skeleton: `pyproject.toml`, venv, `server.py` with instructions, guide resources, both prompts, the 4 environment tools | `ifs-py` connects; list/add/use/remove give the same JSON as TypeScript on a copy of `config.json`; guides list and read the same |
| 2 | Auth: sessions, OAuth manager, callback server, `start_oauth` + login page, `get_session_info`, client_credentials | Browser login to the test instance through `ifs-py` works; `session.json` is still readable by the TypeScript server, and the other way round; refresh works after expiry |
| 3 | API: `api_client`, `call_protected_api`, `get_api_guide`, `export_api_data` | Same navigator query as TypeScript returns the same data; the over-100 KB path triggers; CSV export of a list matches TypeScript byte for byte |
| 4 | Skills: HAR + OpenAPI parsers, `parse_har_file`, `read_openapi_file`, `save_skill`, `import_skill` | Same summaries as TypeScript for one HAR file and one OpenAPI file; save/import of a test skill into a scratch `SKILLS_DIR` |
| 5 | Tests + CI: pytest for the 15 rules above and the parsers; ruff; a test replacing `check-secret-access.mjs` (only `oauth.py` may call `get_client_secret`); GitHub Actions running ruff + pytest on 3.10 and 3.13 | CI green |
| 6 | Cutover: move `python/` to the root; plugin `.mcp.json` runs the Python server; remove `src/`, `package.json`, `package-lock.json`, `tsconfig.json`, `manifest.json`, `.mcpbignore`, Node CI scripts; update README / INSTALLATION / CONFIGURATION; version 2.0.0; remove `ifs-py` | `/mcp` shows the plugin connected on Python; login + a GET call work; no Node needed |

Per the usual rule: test after each phase, **one commit at the end**. The commit message is
shown before committing.

## What changes for users

- **Claude Code / Codex / other MCP clients:** need Python ≥ 3.10 and a one-time
  `pip install -e .` (or `pipx install`). No more `npm install && npm run build`.
- **Claude Desktop one-click `.mcpb`:** dropped in 2.0.0. A Python `.mcpb` needs Python on
  the machine or bundled dependencies. Can be added later if wanted.
- **Upstream:** after the cutover, `git merge upstream/main` no longer applies. knakit fixes
  are ported by hand. `upstream` stays as a remote for reading their changes.

## Open questions

1. **Keep the TypeScript version after the cutover?** Plan: delete it (dead code), since git
   history keeps it.
2. **Claude Desktop support needed?** Plan: no, Claude Code only for now.
3. **Package / command name:** plan `ifs-cloud-mcp-bridge` / `ifs_mcp` / `ifs-mcp`.
4. **Tool names:** keep the 13 names unchanged (recommended, so existing skills and prompts
   keep working), or rename them now while there are no other users?
