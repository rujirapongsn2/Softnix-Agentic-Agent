from pathlib import Path

from softnix_agentic_agent.skills.loader import SkillLoader
from softnix_agentic_agent.skills.parser import parse_skill_file


def test_parse_skill_with_metadata_and_refs(tmp_path: Path) -> None:
    skill_dir = tmp_path / "s1"
    (skill_dir / "assets").mkdir(parents=True)
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "assets" / "a.md").write_text("A", encoding="utf-8")
    (skill_dir / "scripts" / "b.sh").write_text("#!/bin/sh", encoding="utf-8")

    skill = skill_dir / "SKILL.md"
    skill.write_text(
        """---
name: skill-a
description: desc-a
---

Use [asset](assets/a.md)
And scripts/b.sh
""",
        encoding="utf-8",
    )

    parsed = parse_skill_file(skill)
    assert parsed.name == "skill-a"
    assert parsed.description == "desc-a"
    assert len(parsed.references) == 2


def test_loader_lists_skills(tmp_path: Path) -> None:
    d1 = tmp_path / "one"
    d1.mkdir(parents=True)
    (d1 / "SKILL.md").write_text("Simple skill", encoding="utf-8")

    loader = SkillLoader(tmp_path)
    items = loader.list_skills()
    assert len(items) == 1
    assert items[0].name == "one"


def test_loader_select_skills_returns_ranked_subset(tmp_path: Path) -> None:
    web = tmp_path / "web-summary"
    web.mkdir(parents=True)
    (web / "SKILL.md").write_text(
        """---
name: web-summary
description: summarize website by url
---
Use for web summary tasks.
""",
        encoding="utf-8",
    )
    other = tmp_path / "local-ops"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("File ops only", encoding="utf-8")

    loader = SkillLoader(tmp_path)
    selected = loader.select_skills(task="สรุปเว็บ https://example.com", limit=1)
    assert len(selected) == 1
    assert selected[0].name == "web-summary"
