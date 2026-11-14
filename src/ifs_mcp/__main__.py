"""Entry point: python -m ifs_mcp  (or the ifs-mcp command)."""

from __future__ import annotations

from pathlib import Path

import anyio
from dotenv import load_dotenv

from .auth.oauth import OAuthManager
from .auth.sessions import initialize_token_store
from .server import run


def _project_root() -> Path | None:
    """The folder holding pyproject.toml, for a source checkout; None when installed."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def main() -> None:
    # Load .env from the project root, not the working folder (MCP hosts launch from anywhere).
    root = _project_root()
    if root and (root / ".env").exists():
        load_dotenv(root / ".env")
    oauth = OAuthManager()
    initialize_token_store()
    anyio.run(run, oauth)


if __name__ == "__main__":
    main()
