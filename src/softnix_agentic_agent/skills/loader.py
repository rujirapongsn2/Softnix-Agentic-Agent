from __future__ import annotations

from pathlib import Path
import re

from softnix_agentic_agent.skills.parser import SkillDefinition, parse_skill_file


class SkillLoader:
    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root

    def list_skills(self) -> list[SkillDefinition]:
        if not self.skills_root.exists():
            return []
        skills: list[SkillDefinition] = []
        for skill_md in self.skills_root.glob("**/SKILL.md"):
            skills.append(parse_skill_file(skill_md))
        return sorted(skills, key=lambda s: s.name.lower())

    def render_compact_context(self, task: str = "", limit: int = 8) -> str:
        skills = self.select_skills(task=task, limit=limit)
        if not skills:
            return "No skills found."

        lines = []
        for s in skills:
            if s.references:
                lines.append(f"- {s.name}: {s.description} | references={len(s.references)} files")
            else:
                lines.append(f"- {s.name}: {s.description}")

            script_refs = self._script_reference_paths(s)
            if script_refs:
                lines.append(f"  scripts: {', '.join(script_refs[:3])}")

            # Include a short actionable excerpt for relevant skills so behavior is guided by SKILL.md.
            excerpt = self._short_body_excerpt(s.body, max_lines=8)
            if excerpt:
                for ln in excerpt.splitlines():
                    lines.append(f"  {ln}")
        lines.append(
            "Note: skill scripts/references under skills_dir are trusted read-only inputs; "
            "copy to workspace before modification."
        )
        return "\n".join(lines)

    def select_skills(self, task: str = "", limit: int = 8) -> list[SkillDefinition]:
        all_skills = self.list_skills()
        if not all_skills:
            return []
        ranked = self._rank_skills(task, all_skills)
        return ranked[:limit]

    def _rank_skills(self, task: str, skills: list[SkillDefinition]) -> list[SkillDefinition]:
        task_text = (task or "").strip().lower()
        if not task_text:
            return skills

        task_tokens = {t for t in re.findall(r"[a-z0-9ก-๙_-]+", task_text) if len(t) >= 2}

        def score(skill: SkillDefinition) -> tuple[int, str]:
            blob = f"{skill.name} {skill.description} {skill.body}".lower()
            token_hits = sum(1 for t in task_tokens if t in blob)
            url_bonus = 2 if ("http://" in task_text or "https://" in task_text) and "web" in blob else 0
            return (token_hits + url_bonus, skill.name.lower())

        scored = sorted(skills, key=score, reverse=True)
        return scored

    def _short_body_excerpt(self, body: str, max_lines: int = 4) -> str:
        rows = []
        for line in body.splitlines():
            text = line.strip()
            if not text:
                continue
            if text.startswith("---"):
                continue
            rows.append(text)
            if len(rows) >= max_lines:
                break
        return "\n".join(rows)

    def _script_reference_paths(self, skill: SkillDefinition) -> list[str]:
        rows: list[str] = []
        for ref in skill.references:
            try:
                rel = ref.resolve().relative_to(skill.path.parent.resolve())
            except ValueError:
                continue
            text = str(rel).replace("\\", "/")
            if text.startswith("scripts/"):
                rows.append(text)
        return rows
