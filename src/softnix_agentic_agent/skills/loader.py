from __future__ import annotations

from pathlib import Path
import re

from softnix_agentic_agent.skills.parser import SkillDefinition, parse_skill_file


class SkillLoader:
    _DOMAIN_STOPWORDS = {
        "www",
        "http",
        "https",
        "com",
        "co",
        "th",
        "net",
        "org",
        "ai",
        "io",
    }
    _TASK_STOPWORDS = {
        "skill",
        "skills",
        "ช่วย",
        "ให้",
        "ใช้",
        "ต้องการ",
        "หน่อย",
        "ครับ",
        "ค่ะ",
        "คะ",
        "na",
    }

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

        skills_root_abs = str(self.skills_root.resolve())
        lines = []
        for s in skills:
            if s.references:
                lines.append(f"- {s.name}: {s.description} | references={len(s.references)} files")
            else:
                lines.append(f"- {s.name}: {s.description}")

            script_refs = self._script_reference_paths(s)
            if script_refs:
                lines.append(f"  scripts: {', '.join(script_refs[:3])}")
            success_artifacts = getattr(s, "success_artifacts", []) or []
            if success_artifacts:
                lines.append(f"  success_artifacts: {', '.join(success_artifacts[:5])}")

            # Include a short actionable excerpt for relevant skills so behavior is guided by SKILL.md.
            excerpt = self._short_body_excerpt(s.body, max_lines=8)
            if excerpt:
                for ln in excerpt.splitlines():
                    lines.append(f"  {ln}")
        lines.append(
            f"Note: skills_dir absolute path is `{skills_root_abs}` (outside workspace in many setups)."
        )
        lines.append(
            "Use absolute script/reference paths above when reading skill files; "
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

        task_tokens = self._extract_task_tokens(task_text)
        explicit_mentions = self._extract_explicit_skill_mentions(task_text=task_text)
        task_has_url = (
            "http://" in task_text
            or "https://" in task_text
            or bool(re.search(r"\bwww\.[a-z0-9.-]+", task_text))
        )
        task_has_search_intent = self._task_has_search_intent(task_text)
        task_has_email_intent = self._task_has_email_intent(task_text)

        def score(skill: SkillDefinition) -> tuple[int, int, str]:
            refs_blob = " ".join(str(ref.name).lower() for ref in skill.references)
            name_desc_blob = f"{skill.name} {skill.description}".lower()
            token_hits = sum(1 for t in task_tokens if self._token_in_blob(token=t, blob=name_desc_blob))
            ref_hits = sum(1 for t in task_tokens if self._token_in_blob(token=t, blob=refs_blob))
            token_hits += ref_hits
            intent_bonus = 2 if task_has_search_intent and self._is_search_or_news_skill(name_desc_blob) else 0
            email_bonus = 3 if task_has_email_intent and self._is_email_related(name_desc_blob) else 0
            url_bonus = 2 if task_has_url and self._is_web_related(name_desc_blob) else 0
            if task_has_url and (not task_has_search_intent) and self._is_search_or_news_skill(name_desc_blob):
                url_bonus = 0
            explicit_bonus = 100 if skill.name.lower() in explicit_mentions else 0
            total = token_hits + intent_bonus + email_bonus + url_bonus + explicit_bonus
            # Keep components in tuple for deterministic sorting and filtering.
            return (total, token_hits + intent_bonus + email_bonus + url_bonus, skill.name.lower())

        scored_rows: list[tuple[SkillDefinition, tuple[int, int, str]]] = []
        for skill in skills:
            scored_rows.append((skill, score(skill)))
        scored_rows.sort(key=lambda item: item[1], reverse=True)

        filtered: list[SkillDefinition] = []
        for skill, (total, non_explicit_score, _) in scored_rows:
            # Keep explicitly requested skills even if lexical score is low.
            if skill.name.lower() in explicit_mentions:
                filtered.append(skill)
                continue
            # Keep only relevant skills; this avoids pulling unrelated skill context every run.
            if non_explicit_score > 0:
                filtered.append(skill)

        return filtered

    def _extract_explicit_skill_mentions(self, task_text: str) -> set[str]:
        mentions: set[str] = set()
        for match in re.findall(r"\$([a-z0-9][a-z0-9_-]{1,63})", task_text):
            mentions.add(match.lower())
        return mentions

    def _extract_task_tokens(self, task_text: str) -> set[str]:
        raw_tokens = {t for t in re.findall(r"[a-z0-9ก-๙_-]+", task_text) if len(t) >= 2}
        normalized: set[str] = set()
        for token in raw_tokens:
            if token in self._DOMAIN_STOPWORDS or token in self._TASK_STOPWORDS:
                continue
            if re.fullmatch(r"[a-z0-9_-]+", token) and len(token) < 3:
                continue
            normalized.add(token)
        return normalized

    def _token_in_blob(self, token: str, blob: str) -> bool:
        if re.search(r"[ก-๙]", token):
            return token in blob
        return bool(re.search(rf"(?<![a-z0-9_-]){re.escape(token)}(?![a-z0-9_-])", blob))

    def _is_web_related(self, blob: str) -> bool:
        english_keywords = ("web", "website", "url", "browser", "crawl", "fetch", "search", "news")
        for keyword in english_keywords:
            if re.search(rf"(?<![a-z0-9_-]){re.escape(keyword)}(?![a-z0-9_-])", blob):
                return True
        return ("เว็บไซต์" in blob) or ("เว็บ" in blob)

    def _is_search_or_news_skill(self, blob: str) -> bool:
        english_markers = ("tavily", "search", "query", "news")
        for marker in english_markers:
            if re.search(rf"(?<![a-z0-9_-]){re.escape(marker)}(?![a-z0-9_-])", blob):
                return True
        return ("ข่าว" in blob) or ("ค้นหา" in blob)

    def _task_has_search_intent(self, task_text: str) -> bool:
        markers = ("search", "query", "find", "news", "ค้นหา", "ข่าว", "หาให้")
        return any(marker in task_text for marker in markers)

    def _task_has_email_intent(self, task_text: str) -> bool:
        markers = ("email", "e-mail", "mail", "อีเมล", "ส่งเมล", "ส่งอีเมล์")
        return any(marker in task_text for marker in markers)

    def _is_email_related(self, blob: str) -> bool:
        markers = ("email", "mail", "resend", "smtp", "อีเมล")
        return any(marker in blob for marker in markers)

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
            resolved = ref.resolve()
            try:
                rel = resolved.relative_to(skill.path.parent.resolve())
            except ValueError:
                continue
            rel_text = str(rel).replace("\\", "/")
            if rel_text.startswith("scripts/"):
                rows.append(str(resolved))
        return rows
