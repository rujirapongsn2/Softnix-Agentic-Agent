from pathlib import Path

from softnix_agentic_agent.agent.task_contract import PathDiscoveryPolicy, TaskContractParser


def test_task_contract_parser_separates_inputs_outputs_and_hints() -> None:
    parser = TaskContractParser()
    contract = parser.parse(
        "จาก input/invoice.pdf ให้ extract ข้อมูลและบันทึกลง output/result.json พร้อม log ที่ logs/run.log"
    )

    assert "input/invoice.pdf" in contract.source_inputs
    assert "output/result.json" in contract.required_outputs
    assert "logs/run.log" in contract.required_outputs
    assert "input" in contract.hinted_directories
    assert "output" in contract.hinted_directories
    assert contract.required_absent == []


def test_task_contract_parser_ignores_non_file_like_identifiers() -> None:
    parser = TaskContractParser()
    contract = parser.parse(
        "สร้าง skill send email โดยมี resend.api_key='re_xxx' และส่งไปที่ rujirapong@gmail.com จากนั้นบันทึกลง result.txt"
    )

    assert "result.txt" in contract.required_outputs
    assert "resend.api_key" not in contract.required_outputs
    assert "gmail.com" not in contract.required_outputs


def test_task_contract_parser_infers_required_absent_for_delete_tasks() -> None:
    parser = TaskContractParser()
    contract = parser.parse("ลบ output.txt และลบ reports/result.json ออกจาก workspace")

    assert "output.txt" in contract.required_absent
    assert "reports/result.json" in contract.required_absent


def test_task_contract_parser_infers_python_modules_and_expected_text_markers() -> None:
    parser = TaskContractParser()
    contract = parser.parse(
        "สร้างสคริปต์ install_and_check.py: ติดตั้ง package humanize ด้วย pip, import humanize, "
        "print เวอร์ชัน humanize และบันทึกลง result.txt ที่มีข้อความ 'ok'"
    )

    assert "humanize" in contract.required_python_modules
    assert "ok" in contract.expected_text_markers


def test_path_discovery_policy_prefers_hinted_directories(tmp_path: Path) -> None:
    (tmp_path / "inputs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "inputs" / "invoice.pdf").write_text("a", encoding="utf-8")
    (tmp_path / "docs" / "invoice.pdf").write_text("b", encoding="utf-8")

    policy = PathDiscoveryPolicy()
    candidates = policy.find_candidates(
        workspace=tmp_path,
        missing_path="invoice.pdf",
        hinted_directories=["inputs"],
        limit=2,
    )

    assert candidates[0] == "inputs/invoice.pdf"


def test_path_discovery_policy_uses_missing_parent_parts_for_ranking(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "archive").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "invoice.pdf").write_text("a", encoding="utf-8")
    (tmp_path / "archive" / "invoice.pdf").write_text("b", encoding="utf-8")

    policy = PathDiscoveryPolicy()
    candidates = policy.find_candidates(
        workspace=tmp_path,
        missing_path="data/invoice.pdf",
        hinted_directories=[],
        limit=2,
    )

    assert candidates[0] == "data/invoice.pdf"
