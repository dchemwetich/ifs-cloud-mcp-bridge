# Contributing to MCP Server for IFS Cloud

Thank you for your interest in contributing. There are three main ways to help:

1. **Share a skill** - Build a skill for an IFS workflow and submit it so others can use it
2. **Report a bug** - Something isn't working as expected
3. **Suggest an improvement** - An idea for a new feature or a better way to do something

---

## Sharing a Skill

Skills are the most valuable contribution you can make. Every skill you share saves someone else hours of figuring out which IFS endpoints to use and what the fields mean.

### What makes a good contributed skill

- **Focused** - one IFS projection or business area per file (Customer Orders, Purchase Orders, Supplier Invoices, etc.)
- **Business-readable** - written in plain language, not just raw API field names
- **Generic** - no real order numbers, customer IDs, or company-specific data. Use placeholders like `CUST-001`, `ORDER-10001`
- **Tested** - you've actually used it to query your IFS instance

See the [Skill Authoring Guide](docs/guides/SKILL_AUTHORING.md) for the full process of building a skill from scratch.

### How to submit a skill

Community maintained skills can be found in [IFS Skills](https://github.com/knakit/ifs-mcp-skills). Check the contribution guide on making a new skill.

## Reporting a Bug

Open an issue at [GitHub Issues](https://github.com/dchemwetich/ifs-cloud-mcp-bridge/issues) and include:

**For authentication issues:**
- Your IFS Cloud version (if known)
- Operating system and Python version (`python --version`)
- The error message from your AI agent or the MCP server

**For skill or API issues:**
- Which skill file you're using
- The `call_protected_api` call that failed (remove any sensitive data)
- The error response

**For build or setup issues:**
- Operating system
- Python version (`python --version`)
- The full error output from `pip install -e .` or the server startup

A good bug report includes enough detail for someone else to reproduce the problem without access to your IFS instance.

---

## Suggesting an Improvement

Open an issue and label it **enhancement**. Describe:

- What you're trying to do
- What you'd expect the tool to do
- Why the current behaviour doesn't work for your case

No suggestion is too small. If something feels harder than it should be, it's worth raising.

---

## Code Contributions

For bug fixes or small improvements, open a PR with a clear description of what you changed and why.

For larger changes (new tools, architectural changes), open an issue first to discuss the approach before writing code - this avoids wasted effort if the direction doesn't fit the project.

### Development Setup

**1. Clone and install**
```bash
git clone https://github.com/dchemwetich/ifs-cloud-mcp-bridge
cd ifs-cloud-mcp-bridge
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
.venv/bin/python -m pip install -e ".[dev]"         # macOS / Linux
```
The install is editable, so code changes take effect the next time the server starts. There is no build step.

**2. Configure (optional)**

Environments are normally registered through chat (`add_ifs_environment`). For a fixed single-environment setup, copy `.env.example` to `.env` and fill in `API_BASE_URL`, `OAUTH_REALM` and `OAUTH_CLIENT_ID`. Values in `.env` or the process environment override `~/.ifs-mcp/config.json`.

**3. Connect it to a client to test against**

**Claude Code** - the repo ships `.mcp.json` and `.claude-plugin/`:
```bash
claude --plugin-dir . --mcp-config ./.mcp.json   # session-only, run /reload-plugins after edits
```
(`--mcp-config` is required alongside `--plugin-dir` - see [anthropics/claude-code#15308](https://github.com/anthropics/claude-code/issues/15308).) For a persistent install instead: `claude plugin marketplace add .` then `claude plugin install ifs-mcp-server@ifs-local`.

**Codex CLI and other MCP hosts** - register the launcher as a stdio server:
```bash
codex mcp add ifs -- python /absolute/path/to/ifs-cloud-mcp-bridge/launch.py
```

### Project layout

| Path | Contents |
|---|---|
| `src/ifs_mcp/server.py` | MCP handlers, server instructions |
| `src/ifs_mcp/tools/` | The 13 tools (`env`, `auth`, `api`, `skills`) |
| `src/ifs_mcp/auth/` | OAuth (PKCE, refresh, client credentials), sessions, callback server |
| `src/ifs_mcp/api_client.py` | Authenticated calls and the host / header / read-only guards |
| `src/ifs_mcp/parsers/` | HAR and OpenAPI summaries for skill authoring |
| `src/ifs_mcp/resources/` | Bundled skill guides |
| `tests/` | pytest suite |

### Before submitting a PR

- [ ] `ruff check src tests launch.py` passes
- [ ] `pytest` passes (it also checks that only `auth/oauth.py` reads a client secret, and that the versions in `pyproject.toml`, `src/ifs_mcp/__init__.py` and `.claude-plugin/plugin.json` match)
- [ ] Existing skills in `src/ifs_mcp/resources/` still load correctly
- [ ] No secrets or credentials in any committed file

CI runs ruff and pytest on Python 3.10 and 3.13, on Ubuntu and Windows.

---

## Questions

If you're unsure whether something is a bug or just unexpected behaviour, or if you want to check whether a skill idea is a good fit before building it - open a Discussion or Issue. Happy to help.
