from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class FallbackDecision:
    sufficient: bool
    reasons: list[str]
    content_length: int
    matched_keywords: list[str]
    required_keywords: list[str]

    def to_dict(self) -> dict:
        return {
            "sufficient": self.sufficient,
            "reasons": self.reasons,
            "content_length": self.content_length,
            "matched_keywords": self.matched_keywords,
            "required_keywords": self.required_keywords,
        }


def decide_web_fallback(
    extracted_text: str,
    *,
    task_hint: str = "",
    min_chars: int = 1200,
    required_keywords: list[str] | None = None,
) -> FallbackDecision:
    text = (extracted_text or "").strip()
    reasons: list[str] = []
    matched: list[str] = []

    if len(text) < int(min_chars):
        reasons.append(f"content_too_short:{len(text)}<{int(min_chars)}")

    candidates: list[str] = []
    if required_keywords:
        candidates.extend([x.strip() for x in required_keywords if x.strip()])
    else:
        # Infer coarse keyword candidates from task hint for lightweight gating.
        for tok in re.findall(r"[A-Za-z0-9ก-๙_-]{4,}", task_hint or ""):
            low = tok.lower()
            if low in {"http", "https", "www", "news", "summary", "สรุป"}:
                continue
            candidates.append(tok)

    uniq_keywords: list[str] = []
    seen = set()
    for kw in candidates:
        k = kw.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq_keywords.append(kw)
        if len(uniq_keywords) >= 8:
            break

    low_text = text.lower()
    for kw in uniq_keywords:
        if kw.lower() in low_text:
            matched.append(kw)

    if uniq_keywords and len(matched) == 0:
        reasons.append("required_keywords_missing")

    sufficient = len(reasons) == 0
    return FallbackDecision(
        sufficient=sufficient,
        reasons=reasons,
        content_length=len(text),
        matched_keywords=matched,
        required_keywords=uniq_keywords,
    )
