"""The package, pyproject and Claude Code plugin manifest must carry the same version."""

import json
import re
from pathlib import Path

import ifs_mcp

ROOT = Path(__file__).resolve().parent.parent


def test_versions_match():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    assert ifs_mcp.__version__ == pyproject == plugin
