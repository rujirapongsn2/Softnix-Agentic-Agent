from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import re


@dataclass
class SkillDefinition:
    name: str
    description: str
    body: str
    path: Path
    references: list[Path]
    success_artifacts: list[str]


def parse_skill_file(skill_file: Path) -> SkillDefinition:
    raw = skill_file.read_text(encoding="utf-8")
    name = skill_file.parent.name
    description = ""
    success_artifacts: list[str] = []
    body = raw

    if raw.startswith("---\n"):
        parts = raw.split("---\n", 2)
        if len(parts) == 3:
            _, meta_block, body_block = parts
            body = body_block.strip()
            lines = meta_block.splitlines()
            for idx, line in enumerate(lines):
                if line.lower().startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.lower().startswith("description:"):
                    description = line.split(":", 1)[1].strip()
                elif line.lower().startswith("success_artifacts:"):
                    tail = line.split(":", 1)[1].strip()
                    success_artifacts = _parse_meta_list(tail=tail, lines=lines[idx + 1 :])

    if not description:
        for line in body.splitlines():
            if line.strip() and not line.strip().startswith("#"):
                description = line.strip()
                break

    references = _resolve_references(body, skill_file.parent)
    return SkillDefinition(
        name=name,
        description=description,
        body=body,
        path=skill_file,
        references=references,
        success_artifacts=success_artifacts,
    )


def _parse_meta_list(tail: str, lines: list[str]) -> list[str]:
    if tail:
        if tail.startswith("[") and tail.endswith("]"):
            try:
                parsed = ast.literal_eval(tail)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                return []
        return [item.strip() for item in tail.split(",") if item.strip()]

    items: list[str] = []
    for line in lines:
        raw = line.strip()
        if not raw.startswith("- "):
            break
        value = raw[2:].strip()
        if value:
            items.append(value)
    return items


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
