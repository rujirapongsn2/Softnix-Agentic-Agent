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


def test_parse_skill_metadata_success_artifacts(tmp_path: Path) -> None:
    skill_dir = tmp_path / "sendmail"
    skill_dir.mkdir(parents=True)
    skill = skill_dir / "SKILL.md"
    skill.write_text(
        """---
name: sendmail
description: send email
success_artifacts:
  - resend_email/result.json
---
Use sendmail skill.
""",
        encoding="utf-8",
    )
    parsed = parse_skill_file(skill)
    assert parsed.success_artifacts == ["resend_email/result.json"]


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


def test_loader_select_skills_filters_irrelevant_skills(tmp_path: Path) -> None:
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
    sendmail = tmp_path / "sendmail"
    sendmail.mkdir(parents=True)
    (sendmail / "SKILL.md").write_text(
        """---
name: sendmail
description: send email by resend
---
Use for email tasks.
""",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    selected = loader.select_skills(task="ช่วยสรุปข้อมูลจาก https://example.com")
    names = [s.name for s in selected]
    assert names == ["web-summary"]


def test_loader_select_skills_keeps_explicit_skill_mentions(tmp_path: Path) -> None:
    tavily = tmp_path / "tavily-search"
    tavily.mkdir(parents=True)
    (tavily / "SKILL.md").write_text(
        """---
name: tavily-search
description: search news via tavily
---
Use for search.
""",
        encoding="utf-8",
    )
    sendmail = tmp_path / "sendmail"
    sendmail.mkdir(parents=True)
    (sendmail / "SKILL.md").write_text(
        """---
name: sendmail
description: send email by resend
---
Use for email tasks.
""",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    selected = loader.select_skills(task="ช่วยใช้ $tavily-search เพื่อสรุปข่าววันนี้")
    names = [s.name for s in selected]
    assert "tavily-search" in names
    assert "sendmail" not in names


def test_loader_select_skills_ignores_domain_tokens_false_positive(tmp_path: Path) -> None:
    web_intel = tmp_path / "web-intel"
    web_intel.mkdir(parents=True)
    (web_intel / "SKILL.md").write_text(
        """---
name: web-intel
description: collect and summarize website content
---
Use for web research and extraction.
""",
        encoding="utf-8",
    )
    tavily = tmp_path / "tavily-search"
    tavily.mkdir(parents=True)
    (tavily / "SKILL.md").write_text(
        """---
name: tavily-search
description: search web and news
---
Use for web search.
""",
        encoding="utf-8",
    )
    sendmail = tmp_path / "sendmail"
    sendmail.mkdir(parents=True)
    (sendmail / "SKILL.md").write_text(
        """---
name: sendmail
description: send email by resend
---
Use for email tasks and company updates.
""",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    selected = loader.select_skills(task="ช่วยสรุปข้อมูลสินค้าและบริการใน www.softnix.co.th")
    names = [s.name for s in selected]
    assert "web-intel" in names
    assert "tavily-search" not in names
    assert "sendmail" not in names


def test_loader_select_skills_prefers_search_skill_for_search_intent(tmp_path: Path) -> None:
    tavily = tmp_path / "tavily-search"
    tavily.mkdir(parents=True)
    (tavily / "SKILL.md").write_text(
        """---
name: tavily-search
description: search news via tavily
---
Use for search tasks.
""",
        encoding="utf-8",
    )
    web = tmp_path / "web-summary"
    web.mkdir(parents=True)
    (web / "SKILL.md").write_text(
        """---
name: web-summary
description: summarize website content
---
Use for web summary tasks.
""",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    selected = loader.select_skills(task="ช่วยค้นหาข่าว AI วันนี้")
    names = [s.name for s in selected]
    assert "tavily-search" in names


def test_loader_render_context_uses_absolute_script_paths_and_skills_dir_note(tmp_path: Path) -> None:
    skill_dir = tmp_path / "resend-email"
    (skill_dir / "scripts").mkdir(parents=True)
    script_file = skill_dir / "scripts" / "send_email.py"
    script_file.write_text("print('ok')\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        """---
name: resend-email
description: send email by resend
---
Use script scripts/send_email.py
""",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    text = loader.render_compact_context(task="", limit=5)
    assert str(tmp_path.resolve()) in text
    assert str(script_file.resolve()) in text


def test_loader_select_skills_email_task_does_not_pull_unrelated_skills(tmp_path: Path) -> None:
    resend = tmp_path / "resend-email"
    resend.mkdir(parents=True)
    (resend / "SKILL.md").write_text(
        """---
name: resend-email
description: send email by resend api
---
Use for sending email.
""",
        encoding="utf-8",
    )
    web_summary = tmp_path / "web-summary"
    web_summary.mkdir(parents=True)
    (web_summary / "SKILL.md").write_text(
        """---
name: web-summary
description: summarize website from url
---
Use for website summary.
""",
        encoding="utf-8",
    )
    web_intel = tmp_path / "web-intel"
    web_intel.mkdir(parents=True)
    (web_intel / "SKILL.md").write_text(
        """---
name: web-intel
description: collect dynamic website data
---
Use for dynamic pages.
""",
        encoding="utf-8",
    )

    loader = SkillLoader(tmp_path)
    selected = loader.select_skills(task="ใช้ skill ส่งอีเมลไปที่ rujirapong@gmail.com")
    names = [s.name for s in selected]
    assert names == ["resend-email"]
