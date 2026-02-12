from softnix_agentic_agent.integrations.telegram_templates import FINAL_OUTPUT_MAX_CHARS, final_run_text


def test_final_run_text_truncates_output_to_4000_chars() -> None:
    raw = "A" * (FINAL_OUTPUT_MAX_CHARS + 200)
    text = final_run_text(
        run_id="r1",
        status="completed",
        iteration=1,
        max_iters=10,
        stop_reason="completed",
        output=raw,
    )
    assert "Run r1: completed" in text
    assert "..." in text
    last = text.splitlines()[-1]
    assert len(last) == FINAL_OUTPUT_MAX_CHARS

