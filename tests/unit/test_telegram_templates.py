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


def test_final_run_text_converts_markdown_to_plain_text() -> None:
    raw = (
        "## หัวข้อ\n\n"
        "**ลูกค้า:** SCG\n"
        "### รายการ\n"
        "| รายการ | จำนวน | ราคา |\n"
        "|---|---|---|\n"
        "| Service A | 1 | 100 |\n"
    )
    text = final_run_text(
        run_id="r2",
        status="completed",
        iteration=2,
        max_iters=10,
        stop_reason="completed",
        output=raw,
    )
    assert "##" not in text
    assert "**" not in text
    assert "ลูกค้า: SCG" in text
    assert "รายการ | จำนวน | ราคา" in text
    assert "Service A | 1 | 100" in text
