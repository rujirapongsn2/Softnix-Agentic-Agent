from __future__ import annotations

from pathlib import Path

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

    def render_compact_context(self, limit: int = 8) -> str:
        skills = self.list_skills()[:limit]
        if not skills:
            return "No skills found."

        lines = []
        for s in skills:
            if s.references:
                lines.append(f"- {s.name}: {s.description} | references={len(s.references)} files")
            else:
                lines.append(f"- {s.name}: {s.description}")
        lines.append("Note: skill references are metadata only; do not read outside workspace.")
        return "\n".join(lines)
