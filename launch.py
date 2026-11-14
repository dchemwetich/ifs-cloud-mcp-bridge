"""Start the server for MCP hosts that launch a script (the Claude Code plugin's .mcp.json).

Uses the project's .venv when there is one; otherwise the Python running this file,
which then needs the dependencies installed (pip install -e .).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    # Run under the venv with this process's stdin/stdout, which carry the MCP connection.
    sys.exit(subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve())]))

sys.path.insert(0, str(ROOT / "src"))
try:
    from ifs_mcp.__main__ import main
except ImportError as exc:
    sys.stderr.write(
        f"ifs-cloud-mcp-bridge: missing dependency ({exc}). "
        f"Create the venv first: python -m venv {ROOT / '.venv'} && "
        f"{VENV_PYTHON} -m pip install -e {ROOT}\n"
    )
    sys.exit(1)

main()
