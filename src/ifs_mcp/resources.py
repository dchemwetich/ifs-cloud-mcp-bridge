"""Skill guides served as ifs://<slug>/guide resources.

Folders are rescanned on every request, so a newly saved skill is available at once.
SKILLS_DIR comes first; a file name found there hides the bundled file of the same name.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

BUNDLED_DIR = Path(os.path.abspath(__file__)).parent / "resources"


def read_raw(path: Path | str) -> str:
    """Read text exactly as stored (keeps CRLF line endings, like Node's readFileSync)."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


@dataclass(frozen=True)
class Guide:
    uri: str
    name: str
    description: str
    path: Path

    def definition(self) -> dict[str, str]:
        return {"uri": self.uri, "name": self.name, "description": self.description, "mimeType": "text/markdown"}

    def read(self) -> str:
        return read_raw(self.path)


def skills_dir() -> Path:
    """Where save_skill / import_skill write: SKILLS_DIR, else the bundled folder."""
    custom = os.environ.get("SKILLS_DIR")
    return Path(os.path.abspath(custom)) if custom else BUNDLED_DIR


def _resource_dirs() -> list[Path]:
    dirs: list[Path] = []
    custom = os.environ.get("SKILLS_DIR")
    if custom:
        p = Path(os.path.abspath(custom))
        if p.exists():
            dirs.append(p)
    if BUNDLED_DIR.exists():
        dirs.append(BUNDLED_DIR)
    return dirs


def _discover() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for d in _resource_dirs():
        for f in sorted(os.listdir(d)):
            if f.endswith(".md") and f not in files:
                files[f] = d / f
    return files


def parse_metadata(content: str, filename: str) -> tuple[str, str, str]:
    """(name, description, slug): first '# ' heading, first non-heading line, file name."""
    lines = content.split("\n")
    heading = next((ln for ln in lines if ln.startswith("# ")), None)
    name = re.sub(r"^#\s+", "", heading).strip() if heading else filename.replace(".md", "", 1)
    desc_line = next((ln for ln in lines if ln.strip() != "" and not ln.startswith("#")), None)
    description = re.sub(r"[`*_]", "", desc_line.strip()) if desc_line else name
    slug = filename.replace(".md", "", 1)
    return name, description, slug


def get_guides() -> list[Guide]:
    guides = []
    for filename, path in _discover().items():
        name, description, slug = parse_metadata(read_raw(path), filename)
        guides.append(Guide(uri=f"ifs://{slug}/guide", name=name, description=description, path=path))
    return guides
