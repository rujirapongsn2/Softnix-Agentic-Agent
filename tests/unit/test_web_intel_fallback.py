from softnix_agentic_agent.web_intel.fallback import decide_web_fallback


def test_decide_web_fallback_sufficient_content() -> None:
    text = ("softnix ai platform " * 120).strip()
    decision = decide_web_fallback(text, task_hint="สรุปข้อมูล softnix ai", min_chars=200)
    assert decision.sufficient is True
    assert decision.reasons == []


def test_decide_web_fallback_short_content() -> None:
    decision = decide_web_fallback("short", task_hint="สรุปข้อมูล", min_chars=100)
    assert decision.sufficient is False
    assert any("content_too_short" in r for r in decision.reasons)


def test_decide_web_fallback_missing_required_keywords() -> None:
    decision = decide_web_fallback(
        "this page has generic content",
        min_chars=10,
        required_keywords=["softnix", "logger"],
    )
    assert decision.sufficient is False
    assert "required_keywords_missing" in decision.reasons
