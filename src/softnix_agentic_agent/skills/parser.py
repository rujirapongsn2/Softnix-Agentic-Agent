from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class SkillDefinition:
    name: str
    description: str
    body: str
    path: Path
    references: list[Path]


def parse_skill_file(skill_file: Path) -> SkillDefinition:
    raw = skill_file.read_text(encoding="utf-8")
    name = skill_file.parent.name
    description = ""
    body = raw

    if raw.startswith("---\n"):
        parts = raw.split("---\n", 2)
        if len(parts) == 3:
            _, meta_block, body_block = parts
            body = body_block.strip()
            for line in meta_block.splitlines():
                if line.lower().startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.lower().startswith("description:"):
                    description = line.split(":", 1)[1].strip()

    if not description:
        for line in body.splitlines():
            if line.strip() and not line.strip().startswith("#"):
                description = line.strip()
                break

    references = _resolve_references(body, skill_file.parent)
    return SkillDefinition(name=name, description=description, body=body, path=skill_file, references=references)


def _resolve_references(body: str, base_dir: Path) -> list[Path]:
    refs: list[Path] = []
    for match in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
        rel = match.strip()
        if rel.startswith(("http://", "https://", "mailto:")):
            continue
        p = (base_dir / rel).resolve()
        if p.exists():
            refs.append(p)

    for token in re.findall(r"\b(?:assets|scripts)/[^\s)]+", body):
        p = (base_dir / token).resolve()
        if p.exists() and p not in refs:
            refs.append(p)

    return refs
