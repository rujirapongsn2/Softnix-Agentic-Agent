import json
from pathlib import Path
import itertools

from softnix_agentic_agent.agent.loop import AgentLoopRunner
from softnix_agentic_agent.agent.planner import Planner
from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.providers.base import LLMProvider
from softnix_agentic_agent.storage.filesystem_store import FilesystemStore
from softnix_agentic_agent.types import LLMResponse, ProviderStatus, RunStatus, StopReason


class FakeProvider(LLMProvider):
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.i = 0

    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[override]
        item = self.outputs[min(self.i, len(self.outputs) - 1)]
        self.i += 1
        return LLMResponse(content=json.dumps(item), usage={"total_tokens": 1})

    def healthcheck(self) -> ProviderStatus:
        return ProviderStatus(ok=True, message="ok")


class BrokenJSONProvider(LLMProvider):
    def __init__(self, content: str = "{") -> None:
        self.content = content

    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[override]
        return LLMResponse(content=self.content, usage={"total_tokens": 1})

    def healthcheck(self) -> ProviderStatus:
        return ProviderStatus(ok=True, message="ok")


class FlakyJSONProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[override]
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content="{invalid", usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
        payload = {"done": True, "final_output": "ok", "actions": []}
        return LLMResponse(content=json.dumps(payload), usage={"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11})

    def healthcheck(self) -> ProviderStatus:
        return ProviderStatus(ok=True, message="ok")


class CapturingProvider(LLMProvider):
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.i = 0
        self.user_prompts: list[str] = []

    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[override]
        user_msg = ""
        for m in messages:
            if m.get("role") == "user":
                user_msg = str(m.get("content", ""))
        self.user_prompts.append(user_msg)
        item = self.outputs[min(self.i, len(self.outputs) - 1)]
        self.i += 1
        return LLMResponse(content=json.dumps(item), usage={"total_tokens": 1})

    def healthcheck(self) -> ProviderStatus:
        return ProviderStatus(ok=True, message="ok")


def test_loop_completes(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [{"name": "list_dir", "params": {"path": "."}}],
            },
            {"done": True, "final_output": "done", "actions": []},
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="demo",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=3,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.iteration == 2


def test_loop_max_iters(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="demo",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert state.status == RunStatus.FAILED
    assert state.iteration == 2


def test_loop_auto_completes_answer_only_task_at_max_iters(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "final_output": "สรุปข้อมูลจากเว็บเรียบร้อย",
                "actions": [],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ช่วยสรุปข้อมูลสินค้าและบริการใน www.softnix.co.th",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.status == RunStatus.COMPLETED
    assert state.iteration == 1


def test_loop_does_not_auto_complete_side_effect_task_at_max_iters(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "final_output": "จะสร้างไฟล์ result.txt",
                "actions": [],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="สร้างไฟล์ result.txt แล้วบันทึกผล",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert state.status == RunStatus.FAILED


def test_loop_write_workspace_file_is_snapshotted_as_artifact(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "1111.text", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="create file",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert "1111.text" in store.list_artifacts(state.run_id)


def test_loop_write_file_alias_is_snapshotted_as_artifact(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_file",
                        "params": {"path": "result.txt", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="create result",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert "result.txt" in store.list_artifacts(state.run_id)


def test_loop_run_python_code_output_file_is_snapshotted_as_artifact(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_python_code",
                        "params": {
                            "code": (
                                "from pathlib import Path\n"
                                "Path('softnix_logger_summary.md').write_text('ok', encoding='utf-8')\n"
                                "print('created softnix_logger_summary.md')\n"
                            )
                        },
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="create summary via python",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert "softnix_logger_summary.md" in store.list_artifacts(state.run_id)


def test_loop_run_python_code_out_dir_files_are_snapshotted_as_artifacts(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_python_code",
                        "params": {
                            "code": (
                                "import argparse\n"
                                "from pathlib import Path\n"
                                "p = argparse.ArgumentParser()\n"
                                "p.add_argument('--out-dir', required=True)\n"
                                "a = p.parse_args()\n"
                                "d = Path(a.out_dir)\n"
                                "d.mkdir(parents=True, exist_ok=True)\n"
                                "(d / 'summary.md').write_text('# Web Intel Summary\\n', encoding='utf-8')\n"
                                "(d / 'meta.json').write_text('{\"generated_by\":\"web_intel_fetch.py\",\"timestamp\":\"2026-02-11T00:00:00+00:00\"}\\n', encoding='utf-8')\n"
                                "print('done')\n"
                            ),
                            "args": ["--out-dir", "web_intel"],
                        },
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="create web_intel outputs",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    artifacts = set(store.list_artifacts(state.run_id))
    assert state.stop_reason == StopReason.COMPLETED
    assert "web_intel/summary.md" in artifacts
    assert "web_intel/meta.json" in artifacts


def test_loop_autofills_rm_targets_from_task_when_missing(tmp_path: Path) -> None:
    script = tmp_path / "script.py"
    result = tmp_path / "result.txt"
    script.write_text("print('x')", encoding="utf-8")
    result.write_text("x", encoding="utf-8")

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_safe_command",
                        "params": {"command": "rm -f"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        safe_commands=["rm", "ls", "python", "echo"],
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ลบ script.py และลบ result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert script.exists() is False
    assert result.exists() is False


def test_loop_objective_validation_blocks_done_when_output_missing(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "final_output": "saved result.txt",
                "actions": [],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียนผลลัพธ์ลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "[validation] failed" in state.last_output
    assert "missing output file: result.txt" in state.last_output


def test_loop_objective_validation_blocks_done_when_delete_target_still_exists(tmp_path: Path) -> None:
    (tmp_path / "output.txt").write_text("old", encoding="utf-8")
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "final_output": "deleted output.txt",
                "actions": [],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ลบ output.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "file should be absent but still exists: output.txt" in state.last_output


def test_loop_objective_validation_accepts_delete_when_target_removed(tmp_path: Path) -> None:
    (tmp_path / "output.txt").write_text("old", encoding="utf-8")
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_python_code",
                        "params": {
                            "code": (
                                "from pathlib import Path\n"
                                "Path('output.txt').unlink(missing_ok=True)\n"
                                "print('deleted')\n"
                            )
                        },
                    },
                ],
                "final_output": "deleted",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ลบ output.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert (tmp_path / "output.txt").exists() is False


def test_loop_objective_validation_accepts_valid_file_exists_check(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "result.txt", "content": "ok"},
                    }
                ],
                "validations": [{"type": "file_exists", "path": "result.txt"}],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="create result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert (tmp_path / "result.txt").exists() is True


def test_loop_objective_validation_accepts_json_key_checks(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "meta.json",
                            "content": '{"generated_by":"web_intel_fetch.py","timestamp":"2026-02-11T00:00:00+00:00"}\n',
                        },
                    }
                ],
                "validations": [
                    {"type": "json_key_equals", "path": "meta.json", "key": "generated_by", "value": "web_intel_fetch.py"},
                    {"type": "json_key_exists", "path": "meta.json", "key": "timestamp"},
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="validate json contract",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED


def test_loop_objective_validation_blocks_when_json_key_equals_mismatch(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "meta.json",
                            "content": '{"generated_by":"manual","timestamp":"2026-02-11T00:00:00+00:00"}\n',
                        },
                    }
                ],
                "validations": [
                    {"type": "json_key_equals", "path": "meta.json", "key": "generated_by", "value": "web_intel_fetch.py"}
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="validate json mismatch",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "json key mismatch in meta.json: generated_by" in state.last_output


def test_loop_objective_validation_blocks_done_when_task_requires_numpy_but_script_missing_import(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "calculate_stats.py",
                            "content": "values=[1,2,3]\nprint(sum(values)/len(values))\n",
                        },
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "stats.txt", "content": "ok"},
                    },
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="สร้างสคริปต์ Python ชื่อ calculate_stats.py ใช้ numpy แล้วบันทึกลง stats.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "module not imported in calculate_stats.py: numpy" in state.last_output


def test_loop_objective_validation_accepts_when_task_requires_numpy_and_script_imports_numpy(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "calculate_stats.py",
                            "content": "import numpy as np\nprint(np.mean([1,2,3]))\n",
                        },
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "stats.txt", "content": "ok"},
                    },
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="สร้างสคริปต์ Python ชื่อ calculate_stats.py ใช้ numpy แล้วบันทึกลง stats.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert (tmp_path / "stats.txt").exists() is True


def test_loop_semantic_checks_validate_import_and_expected_text_marker(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "install_and_check.py",
                            "content": "import humanize\nprint(humanize.__version__)\n",
                        },
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "output.txt",
                            "content": "ok\n",
                        },
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "result.txt",
                            "content": "ok\nhumanize 4.12.3\n",
                        },
                    },
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task=(
            "สร้างสคริปต์ Python ชื่อ install_and_check.py ที่ทำ 3 ขั้นตอน: "
            "(1) ติดตั้ง package humanize ด้วย pip "
            "(2) import humanize แล้วสร้างไฟล์ output.txt ที่มีข้อความ 'ok' "
            "(3) print เวอร์ชัน humanize แล้วบันทึกผลลง result.txt"
        ),
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED


def test_loop_semantic_checks_fail_when_expected_marker_missing(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "install_and_check.py",
                            "content": "import humanize\nprint(humanize.__version__)\n",
                        },
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "result.txt",
                            "content": "humanize 4.12.3\n",
                        },
                    },
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task=(
            "สร้างสคริปต์ Python ชื่อ install_and_check.py ที่ทำ 3 ขั้นตอน: "
            "(1) ติดตั้ง package humanize ด้วย pip "
            "(2) import humanize "
            "(3) print เวอร์ชัน humanize แล้วบันทึกผลลง result.txt ที่มีข้อความ 'ok'"
        ),
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "text not found in result.txt: ok" in state.last_output


def test_loop_logs_selected_skills_in_events(tmp_path: Path) -> None:
    skill_dir = tmp_path / "web-summary"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: web-summary
description: summarize website content
---

Use this skill when task contains URL and asks summary.
""",
        encoding="utf-8",
    )

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "stats.txt", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ช่วยสรุปข้อมูล https://example.com",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("skills selected iteration=1 names=web-summary" in e for e in events)


def test_loop_blocks_done_when_web_intel_contract_markers_missing(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "web_intel/summary.md", "content": "# Custom Summary\nmanual\n"},
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "web_intel/meta.json",
                            "content": '{"url":"https://example.com","status":"partial"}\n',
                        },
                    },
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task=(
            "ช่วยสรุปแบบ fetch-first และอ่าน web_intel/summary.md กับ web_intel/meta.json "
            "ก่อนสรุปผลสุดท้าย"
        ),
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "json key not found in web_intel/meta.json: generated_by" in state.last_output


def test_loop_blocks_done_when_web_intel_files_not_produced_in_current_run(tmp_path: Path) -> None:
    web_intel = tmp_path / "web_intel"
    web_intel.mkdir(parents=True, exist_ok=True)
    (web_intel / "summary.md").write_text("# Web Intel Summary\nstale\n", encoding="utf-8")
    (web_intel / "meta.json").write_text(
        '{\n  "generated_by": "web_intel_fetch.py",\n  "timestamp": "2026-01-01T00:00:00+00:00"\n}\n',
        encoding="utf-8",
    )

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [],
                "final_output": "done from stale files",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task=(
            "ช่วยสรุปแบบ fetch-first และอ่าน web_intel/summary.md กับ web_intel/meta.json "
            "ก่อนสรุปผลสุดท้าย"
        ),
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "required web_intel output not produced in this run: web_intel/meta.json" in state.last_output


def test_loop_auto_completes_web_intel_outputs_even_when_done_false(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "web_intel/summary.md", "content": "# Web Intel Summary\nok\n"},
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "web_intel/meta.json",
                            "content": '{"generated_by":"web_intel_fetch.py","timestamp":"2026-02-11T00:00:00+00:00"}\n',
                        },
                    },
                ],
                "final_output": "",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task=(
            "ช่วยสรุปข้อมูลแบบ fetch-first และอ่าน web_intel/summary.md กับ web_intel/meta.json "
            "ก่อนสรุปผล"
        ),
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=3,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.iteration == 1
    artifacts = set(store.list_artifacts(state.run_id))
    assert "web_intel/summary.md" in artifacts
    assert "web_intel/meta.json" in artifacts


def test_loop_infer_output_files_excludes_skill_script_input_path(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": True, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    task = (
        "ช่วยสรุปแบบ fetch-first: รัน python skillpacks/web-intel/scripts/web_intel_fetch.py "
        "--url \"https://www.softnix.ai\" --task-hint \"สรุปข้อมูลสินค้าและข่าว AI\" --out-dir \"web_intel\" "
        "แล้วอ่าน web_intel/summary.md และ web_intel/meta.json"
    )
    inferred = runner._infer_output_files_from_task(task)

    assert "skillpacks/web-intel/scripts/web_intel_fetch.py" not in inferred
    assert "web_intel/summary.md" in inferred
    assert "web_intel/meta.json" in inferred


def test_loop_infer_output_files_ignores_inline_code_identifiers(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": True, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    task = (
        "ช่วยสร้าง skill send email โดยมีตัวอย่างโค้ด resend.api_key='re_xxx' "
        "และส่งไปที่ rujirapong@gmail.com บนโดเมน resend.dev"
    )
    inferred = runner._infer_output_files_from_task(task)

    assert "resend.api_key" not in inferred
    assert "gmail.com" not in inferred
    assert "resend.dev" not in inferred


def test_loop_prepare_run_sanitizes_secret_and_writes_workspace_secret_file(tmp_path: Path) -> None:
    raw_key = "re_testsecret_1234567890abcdef"
    provider = FakeProvider(outputs=[{"done": True, "actions": [], "final_output": "ok"}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task=(
            "ช่วยสร้าง skill send email โดยมีตัวอย่างโค้ด "
            f"resend.api_key = \"{raw_key}\" และกำหนด RESEND_API_KEY={raw_key}"
        ),
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert raw_key not in state.task
    assert "<REDACTED:RESEND_API_KEY>" in state.task
    assert ".secret/RESEND_API_KEY" in state.task
    secret_file = tmp_path / ".secret" / "RESEND_API_KEY"
    assert secret_file.exists()
    assert secret_file.read_text(encoding="utf-8").strip() == raw_key
    events = store.read_events(state.run_id)
    assert any("security policy applied: secrets sanitized" in e for e in events)


def test_loop_validation_resolves_suffix_path_from_produced_files(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "send-email/scripts/send_email.py", "content": "print('ok')\n"},
                    }
                ],
                "validations": [{"type": "file_exists", "path": "scripts/send_email.py"}],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="สร้างไฟล์ send-email/scripts/send_email.py ให้ใช้งานได้",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.status == RunStatus.COMPLETED


def test_loop_materializes_skill_file_for_read_file_action(tmp_path: Path) -> None:
    skills_root = tmp_path / "skillpacks"
    skill_dir = skills_root / "resend-email"
    script = skill_dir / "scripts" / "send_email.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: resend-email
description: send email
---
Use scripts/send_email.py
""",
        encoding="utf-8",
    )
    script.write_text("print('mail-ok')\n", encoding="utf-8")

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [{"name": "read_file", "params": {"path": str(script.resolve())}}],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=skills_root)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ส่งอีเมลด้วย skill",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=skills_root,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.status == RunStatus.COMPLETED
    assert (tmp_path / ".softnix_skill_exec" / "resend-email" / "scripts" / "send_email.py").exists()


def test_loop_materializes_skill_file_for_shell_cat_action(tmp_path: Path) -> None:
    skills_root = tmp_path / "skillpacks"
    skill_dir = skills_root / "resend-email"
    script = skill_dir / "scripts" / "send_email.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: resend-email
description: send email
---
Use scripts/send_email.py
""",
        encoding="utf-8",
    )
    script.write_text("print('mail-ok')\n", encoding="utf-8")

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [{"name": "run_shell_command", "params": {"command": f"cat {script.resolve()}"}}],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=skills_root,
        safe_commands=["ls", "cat", "echo", "python"],
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ส่งอีเมลด้วย skill",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=skills_root,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.status == RunStatus.COMPLETED


def test_loop_auto_complete_web_intel_task_with_skill_script_path_in_prompt(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "web_intel/summary.md", "content": "# Web Intel Summary\nok\n"},
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {
                            "path": "web_intel/meta.json",
                            "content": '{"generated_by":"web_intel_fetch.py","timestamp":"2026-02-11T00:00:00+00:00"}\n',
                        },
                    },
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    task = (
        "ช่วยสรุปข้อมูลจาก https://www.softnix.ai ให้ทำแบบ fetch-first: "
        "ถ้าข้อมูลไม่พอให้รัน python skillpacks/web-intel/scripts/web_intel_fetch.py "
        "--url \"https://www.softnix.ai\" --task-hint \"สรุปข้อมูลสินค้าและข่าว AI\" --out-dir \"web_intel\" "
        "แล้วอ่าน web_intel/summary.md และ web_intel/meta.json"
    )
    state = runner.start_run(
        task=task,
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=3,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.iteration == 1
    events = store.read_events(state.run_id)
    assert any("objective auto-completed from inferred validations" in e for e in events)


def test_loop_normalizes_python3_alias_for_run_python_code(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_python_code",
                        "params": {
                            "python_bin": "python3",
                            "code": "from pathlib import Path\nPath('out.txt').write_text('ok', encoding='utf-8')\n",
                        },
                    }
                ],
                "validations": [{"type": "file_exists", "path": "out.txt"}],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        safe_commands=["python", "ls", "rm"],
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียนผลลัพธ์ลง out.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert (tmp_path / "out.txt").exists() is True


def test_loop_run_shell_command_with_structured_args_can_write_result_file(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_shell_command",
                        "params": {
                            "command": "python",
                            "args": ["-c", "print('humanize version 4.15.0')"],
                            "stdout_path": "result.txt",
                        },
                    }
                ],
                "validations": [{"type": "text_in_file", "path": "result.txt", "contains": "humanize version"}],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        safe_commands=["python", "ls", "rm"],
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="run shell command and save output to result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert (tmp_path / "result.txt").exists() is True


def test_loop_blocks_done_when_prior_iteration_output_contains_failure_signal(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "run_python_code",
                        "params": {"code": "raise RuntimeError('boom')"},
                    }
                ],
            },
            {
                "done": True,
                "final_output": "completed",
                "actions": [],
            },
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ส่งอีเมลขอลาพักร้อน",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "previous iteration failed and no recovery action executed" in state.last_output


def test_loop_blocks_done_when_current_iteration_has_failed_actions(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "final_output": "completed",
                "actions": [
                    {
                        "name": "run_python_code",
                        "params": {"code": "raise RuntimeError('boom')"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="demo",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "current iteration has failed actions" in state.last_output


def test_prepare_action_remaps_skill_script_into_workspace_execution(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    script = skill_root / "sendmail" / "scripts" / "send_with_resend.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('from-skill')\n", encoding="utf-8")

    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=skill_root)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    prepared = runner._prepare_action(
        {"name": "run_python_code", "params": {"path": "sendmail/scripts/send_with_resend.py"}},
        task="send mail",
        workspace=tmp_path,
        skills_root=skill_root,
    )
    params = prepared["params"]
    assert params["path"] == ".softnix_skill_exec/sendmail/scripts/send_with_resend.py"
    assert "from-skill" in params["code"]


def test_prepare_action_rewrites_embedded_skill_script_paths_in_python_code(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    script = skill_root / "web-intel" / "scripts" / "web_intel_fetch.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('web-intel-from-skill')\n", encoding="utf-8")

    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=skill_root)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    code = (
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, 'skills/web-intel/scripts/web_intel_fetch.py', '--url', 'https://x'])\n"
    )
    prepared = runner._prepare_action(
        {"name": "run_python_code", "params": {"code": code}},
        task="fetch first",
        workspace=tmp_path,
        skills_root=skill_root,
    )
    params = prepared["params"]
    rewritten = str(params["code"])
    assert "__softnix_skill_files" in rewritten
    assert ".softnix_skill_exec/web-intel/scripts/web_intel_fetch.py" in rewritten
    assert "skills/web-intel/scripts/web_intel_fetch.py" not in rewritten
    assert "web-intel-from-skill" in rewritten


def test_prepare_action_embeds_skill_secret_files_for_skill_script_execution(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    script = skill_root / "tavily-search" / "scripts" / "tavily_search.py"
    secret = skill_root / "tavily-search" / ".secret" / "TAVILY_API_KEY"
    script.parent.mkdir(parents=True, exist_ok=True)
    secret.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('tavily')\n", encoding="utf-8")
    secret.write_text("tvly-test-key\n", encoding="utf-8")

    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=skill_root)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    prepared = runner._prepare_action(
        {"name": "run_python_code", "params": {"path": "tavily-search/scripts/tavily_search.py"}},
        task="search web",
        workspace=tmp_path,
        skills_root=skill_root,
    )

    params = prepared["params"]
    rewritten = str(params["code"])
    assert params["path"] == ".softnix_skill_exec/tavily-search/scripts/tavily_search.py"
    assert "__softnix_skill_secret_files" in rewritten
    assert ".softnix_skill_exec/tavily-search/.secret/TAVILY_API_KEY" in rewritten
    assert "tvly-test-key" in rewritten


def test_prelude_insertion_keeps_future_import_at_top(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    code = (
        "from __future__ import annotations\n"
        "import os\n"
        "print('ok')\n"
    )
    prelude = "from pathlib import Path as __softnix_Path\nprint('p')\n"
    merged = runner._insert_prelude_after_future_imports(code=code, prelude=prelude)
    first_line = merged.splitlines()[0]
    assert first_line == "from __future__ import annotations"
    assert "__softnix_Path" in merged
    assert merged.index("__softnix_Path") > merged.index("from __future__ import annotations")
    compile(merged, "<merged>", "exec")


def test_loop_stops_with_no_progress_before_max_iters(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [{"name": "list_dir", "params": {"path": "."}}],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        no_progress_repeat_threshold=3,
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="demo no progress",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=10,
    )

    assert state.stop_reason == StopReason.NO_PROGRESS
    assert state.status == RunStatus.FAILED
    assert state.iteration < 10
    events = store.read_events(state.run_id)
    assert any("stopped: no_progress detected" in e and "signature=" in e for e in events)


def test_loop_stops_on_repeated_planner_parse_error(tmp_path: Path) -> None:
    provider = BrokenJSONProvider(content="{invalid")
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        planner_parse_error_streak_threshold=2,
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="force parse failures",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=10,
    )

    assert state.stop_reason == StopReason.NO_PROGRESS
    assert state.status == RunStatus.FAILED
    assert state.iteration < 10
    assert "planner_parse_error" in state.last_output
    events = store.read_events(state.run_id)
    assert any("stopped: planner_parse_error streak=" in e for e in events)


def test_loop_stops_on_repeated_capability_failure(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [{"name": "run_shell_command", "params": {"command": "pip", "args": ["install", "x"]}}],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        capability_failure_streak_threshold=2,
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="trigger repeated blocked command",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=10,
    )

    assert state.stop_reason == StopReason.NO_PROGRESS
    assert state.status == RunStatus.FAILED
    assert state.iteration < 10
    assert "capability block" in state.last_output
    events = store.read_events(state.run_id)
    assert any("stopped: capability_block repeated=" in e for e in events)


def test_loop_retries_planner_parse_error_and_recovers(tmp_path: Path) -> None:
    provider = FlakyJSONProvider()
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        planner_retry_on_parse_error=True,
        planner_retry_max_attempts=2,
        planner_parse_error_streak_threshold=3,
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="retry parse error once",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=3,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.status == RunStatus.COMPLETED
    assert provider.calls >= 2
    iterations = store.read_iterations(state.run_id)
    assert len(iterations) == 1
    token_usage = iterations[0].get("token_usage", {})
    assert int(token_usage.get("total_tokens", 0)) >= 23
    events = store.read_events(state.run_id)
    assert any("planner retry attempt=2/2 mode=reduced_context" in e for e in events)
    assert any("planner retry recovered attempt=2" in e for e in events)
    assert any("metrics iteration=1" in e and "planner_attempts=2" in e for e in events)


def test_loop_stops_on_run_wall_time_limit(tmp_path: Path, monkeypatch) -> None:
    provider = FakeProvider(outputs=[{"done": False, "actions": [{"name": "list_dir", "params": {"path": "."}}]}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        run_max_wall_time_sec=2,
        no_progress_repeat_threshold=100,
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    ticks = itertools.count(start=0, step=3)
    monkeypatch.setattr("softnix_agentic_agent.agent.loop.time.monotonic", lambda: float(next(ticks)))

    state = runner.start_run(
        task="long run guard",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=50,
    )

    assert state.stop_reason == StopReason.NO_PROGRESS
    assert state.status == RunStatus.FAILED
    assert "wall time limit" in state.last_output
    events = store.read_events(state.run_id)
    assert any("stopped: wall_time_limit reached" in e for e in events)


def test_loop_list_dir_output_does_not_snapshot_unrelated_existing_files(tmp_path: Path) -> None:
    (tmp_path / "old.txt").write_text("old", encoding="utf-8")

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [{"name": "list_dir", "params": {"path": "."}}],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="just inspect directory",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert "old.txt" not in store.list_artifacts(state.run_id)


def test_loop_auto_completes_when_inferred_output_checks_pass_even_if_done_false(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "result.txt", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียนผลลัพธ์ลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=3,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert state.status == RunStatus.COMPLETED
    events = store.read_events(state.run_id)
    assert any("objective auto-completed from inferred validations" in e for e in events)


def test_loop_auto_complete_does_not_complete_when_current_iteration_has_failed_action(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "result.txt", "content": "ok"},
                    },
                    {
                        "name": "run_python_code",
                        "params": {"code": "raise RuntimeError('boom')"},
                    },
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียนผลลัพธ์ลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    events = store.read_events(state.run_id)
    assert not any("objective auto-completed from inferred validations" in e for e in events)


def test_loop_auto_complete_pytest_requires_pytest_text_in_result(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "test_math.py", "content": "def test_x():\n    assert True\n"},
                    },
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "result.txt", "content": "all tests passed"},
                    },
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="สร้างไฟล์ test_math.py แล้วรัน pytest และบันทึก stdout ลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    assert state.stop_reason == StopReason.MAX_ITERS


def test_loop_auto_complete_does_not_use_stale_inferred_output_from_previous_run(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("stale pytest output", encoding="utf-8")
    provider = FakeProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "test_math.py", "content": "def test_x():\n    assert True\n"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="สร้างไฟล์ test_math.py แล้วรัน pytest พร้อมบันทึก stdout ลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    events = store.read_events(state.run_id)
    assert not any("objective auto-completed from inferred validations" in e for e in events)


def test_loop_infers_pdf_as_input_not_required_output(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": True, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    inferred = runner._infer_output_files_from_task(
        "invoice.pdf แล้วเขียนผลเป็น JSON ลง result.json และสรุปลง result.txt"
    )

    assert "invoice.pdf" not in inferred
    assert "result.json" in inferred
    assert "result.txt" in inferred


def test_loop_validation_blocks_empty_inferred_text_output(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "result.json", "content": ""},
                    }
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียนผลลง result.json",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "output file is empty: result.json" in state.last_output


def test_loop_validation_blocks_stale_inferred_output_not_produced_in_current_run(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("stale", encoding="utf-8")

    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียนผลลัพธ์ลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "inferred output not produced in this run: result.txt" in state.last_output


def test_loop_runtime_guidance_includes_path_recovery_candidates(tmp_path: Path) -> None:
    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    (inputs_dir / "invoice.pdf").write_text("dummy", encoding="utf-8")

    provider = CapturingProvider(
        outputs=[
            {
                "done": False,
                "actions": [
                    {
                        "name": "read_file",
                        "params": {"path": "invoice.pdf"},
                    }
                ],
            },
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "result.json", "content": "{}"},
                    }
                ],
                "final_output": "done",
            },
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="จาก invoice.pdf แล้วเขียนผลลง result.json",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert len(provider.user_prompts) >= 2
    second_prompt = provider.user_prompts[1]
    assert "Previous iteration had missing file/path errors." in second_prompt
    assert "Path recovery:" in second_prompt
    assert "inputs/invoice.pdf" in second_prompt


def test_loop_logs_container_runtime_profile_from_auto_selection(tmp_path: Path) -> None:
    skill_dir = tmp_path / "web-summary"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: web-summary
description: summarize website content
---

Use this skill when task contains URL and asks summary.
""",
        encoding="utf-8",
    )
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "stats.txt", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        exec_runtime="container",
        exec_container_image_profile="auto",
        exec_container_image_base="img-base",
        exec_container_image_web="img-web",
        exec_container_image_data="img-data",
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ช่วยสรุปจาก https://example.com",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("container runtime profile=web image=img-web" in e for e in events)


def test_loop_logs_container_runtime_profile_auto_data_takes_priority_over_web(tmp_path: Path) -> None:
    skill_dir = tmp_path / "web-summary"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: web-summary
description: summarize website content
---
""",
        encoding="utf-8",
    )
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "write_workspace_file",
                        "params": {"path": "stats.txt", "content": "ok"},
                    }
                ],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        exec_runtime="container",
        exec_container_image_profile="auto",
        exec_container_image_base="img-base",
        exec_container_image_web="img-web",
        exec_container_image_data="img-data",
        exec_container_image_scraping="img-scraping",
        exec_container_image_ml="img-ml",
        exec_container_image_qa="img-qa",
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ดึงข้อมูลจาก https://example.com และใช้ numpy คำนวณสถิติ บันทึกลง stats.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("container runtime profile=data image=img-data" in e for e in events)


def test_loop_logs_container_runtime_profile_auto_scraping(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": True, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        exec_runtime="container",
        exec_container_image_profile="auto",
        exec_container_image_base="img-base",
        exec_container_image_web="img-web",
        exec_container_image_data="img-data",
        exec_container_image_scraping="img-scraping",
        exec_container_image_ml="img-ml",
        exec_container_image_qa="img-qa",
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="scrape website with playwright and summarize",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("container runtime profile=scraping image=img-scraping" in e for e in events)


def test_loop_logs_container_runtime_profile_auto_qa(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": True, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        exec_runtime="container",
        exec_container_image_profile="auto",
        exec_container_image_base="img-base",
        exec_container_image_web="img-web",
        exec_container_image_data="img-data",
        exec_container_image_scraping="img-scraping",
        exec_container_image_ml="img-ml",
        exec_container_image_qa="img-qa",
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="run unit test with pytest and generate coverage report",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("container runtime profile=qa image=img-qa" in e for e in events)


def test_loop_logs_container_runtime_profile_auto_data_for_sendmail_task(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": True, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(
        workspace=tmp_path,
        runs_dir=tmp_path / "runs",
        skills_dir=tmp_path,
        exec_runtime="container",
        exec_container_image_profile="auto",
        exec_container_image_base="img-base",
        exec_container_image_web="img-web",
        exec_container_image_data="img-data",
        exec_container_image_scraping="img-scraping",
        exec_container_image_ml="img-ml",
        exec_container_image_qa="img-qa",
    )
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ส่งอีเมลผ่าน resend ไปยังทีม",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("container runtime profile=data image=img-data" in e for e in events)


def test_runtime_guidance_side_effect_task_requires_execution(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    text = runner._build_runtime_guidance(
        task="ใช้ skill ส่งอีเมลขอลาพักร้อน",
        workspace=tmp_path,
        required_outputs=[],
        produced_files=set(),
        previous_actions=[],
        previous_action_results=[],
        objective_stagnation_streak=0,
    )

    assert "Execution objective" in text


def test_runtime_guidance_after_pip_install_requests_rerun(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    previous_actions = [{"name": "run_shell_command", "params": {"command": "pip", "args": ["install", "resend"]}}]
    previous_results = [{"name": "run_safe_command", "ok": True, "output": "Successfully installed resend", "error": None}]
    text = runner._build_runtime_guidance(
        task="ส่งอีเมลผ่าน resend",
        workspace=tmp_path,
        required_outputs=[],
        produced_files=set(),
        previous_actions=previous_actions,
        previous_action_results=previous_results,
        objective_stagnation_streak=0,
    )

    assert "Dependency installation succeeded" in text


def test_loop_uses_skill_success_artifacts_as_required_outputs(tmp_path: Path) -> None:
    skill_dir = tmp_path / "resend-email"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: resend-email
description: send email by resend api
success_artifacts:
  - resend_email/result.json
---
Use for sending email.
""",
        encoding="utf-8",
    )

    provider = FakeProvider(outputs=[{"done": False, "actions": []}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ส่งอีเมลขอลาพักร้อน",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    assert "missing: resend_email/result.json" in state.last_output


def test_loop_execution_gate_replans_preparatory_only_plan(tmp_path: Path) -> None:
    script = tmp_path / "send_email.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    provider = FakeProvider(
        outputs=[
            {"done": False, "actions": [{"name": "read_file", "params": {"path": "send_email.py"}}]},
            {"done": False, "actions": [{"name": "read_file", "params": {"path": "send_email.py"}}]},
            {
                "done": True,
                "final_output": "completed",
                "actions": [{"name": "write_workspace_file", "params": {"path": "result.txt", "content": "ok"}}],
            },
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ส่งอีเมลไปยังทีม",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=2,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("plan gate triggered iteration=2 reason=preparatory_only" in e for e in events)


def test_loop_injects_experience_context_from_success_history(tmp_path: Path) -> None:
    provider = CapturingProvider(
        outputs=[
            {
                "done": True,
                "final_output": "done",
                "actions": [{"name": "write_workspace_file", "params": {"path": "result.txt", "content": "ok"}}],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    store.append_success_experience(
        {
            "run_id": "old-success",
            "status": "completed",
            "task": "สรุปข่าว AI วันนี้",
            "task_tokens": ["สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search"],
            "action_sequence": ["web_fetch", "write_workspace_file"],
            "summary": "สรุปเรียบร้อย",
        },
        max_items=100,
    )
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ช่วยสรุปข่าว AI วันนี้",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert provider.user_prompts
    assert "Experience:" in provider.user_prompts[0]
    assert "Past successful patterns" in provider.user_prompts[0]


def test_loop_records_success_experience_when_completed(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "final_output": "done",
                "actions": [{"name": "write_workspace_file", "params": {"path": "result.txt", "content": "ok"}}],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียน result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    rows = store.read_success_experiences(limit=10)
    assert any(row.get("run_id") == state.run_id for row in rows)


def test_loop_skips_low_signal_experience_for_document_task(tmp_path: Path) -> None:
    provider = FakeProvider(outputs=[{"done": True, "final_output": "ไม่พบไฟล์ pdf", "actions": [{"name": "list_dir", "params": {"path": "."}}]}])
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ช่วยหาไฟล์ pdf แล้วอ่านข้อมูล สรุป ใคร อะไร ที่ไหน อย่างไร",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    rows = store.read_success_experiences(limit=10)
    assert all(row.get("run_id") != state.run_id for row in rows)
    events = store.read_events(state.run_id)
    assert any("experience skipped reason=low_signal_or_preparatory_only" in e for e in events)


def test_loop_records_failure_experience_when_failed(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "final_output": "saved",
                "actions": [{"name": "run_python_code", "params": {"code": "print('noop')"}}],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เขียนผลลัพธ์ลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.MAX_ITERS
    rows = store.read_failure_experiences(limit=20)
    row = next((x for x in rows if x.get("run_id") == state.run_id), None)
    assert row is not None
    assert str(row.get("failure_class", "")).strip() in {"missing_path", "objective_validation_failed"}
    assert "run_python_code" in [str(x).strip() for x in row.get("action_sequence", [])]


def test_loop_injects_failure_strategy_guidance_from_history(tmp_path: Path) -> None:
    provider = CapturingProvider(
        outputs=[
            {
                "done": True,
                "final_output": "done",
                "actions": [{"name": "write_workspace_file", "params": {"path": "result.txt", "content": "ok"}}],
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    store.append_failure_experience(
        {
            "run_id": "old-failure",
            "status": "failed",
            "task": "ช่วยสรุปข่าว AI วันนี้",
            "task_tokens": ["ช่วย", "สรุป", "ข่าว", "ai", "วันนี้"],
            "selected_skills": ["tavily-search"],
            "failure_class": "missing_path",
            "recommended_strategy": "discover path first then continue execution",
        },
        max_items=100,
    )
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="ช่วยสรุปข่าว AI วันนี้ แล้วบันทึกลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    assert provider.user_prompts
    assert "Failure avoidance strategies" in provider.user_prompts[0]


def test_loop_replans_when_plan_repeats_failed_action_sequence(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {"done": False, "actions": [{"name": "run_python_code", "params": {"code": "print('same')"}}]},
            {"done": True, "actions": [{"name": "write_workspace_file", "params": {"path": "result.txt", "content": "ok"}}]},
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    store.append_failure_experience(
        {
            "run_id": "old-fail-seq",
            "status": "failed",
            "task": "สร้างไฟล์ผลลัพธ์จาก python",
            "task_tokens": ["สร้าง", "ไฟล์", "ผลลัพธ์", "python"],
            "selected_skills": [],
            "action_sequence": ["run_python_code"],
            "failure_class": "objective_validation_failed",
            "recommended_strategy": "avoid pure run_python_code-only loop",
        },
        max_items=100,
    )
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="สร้างไฟล์ผลลัพธ์จาก python แล้วบันทึกลง result.txt",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.stop_reason == StopReason.COMPLETED
    events = store.read_events(state.run_id)
    assert any("plan gate triggered iteration=1 reason=repeated_failed_sequence" in e for e in events)


def test_loop_auto_escalation_appends_actionable_message_for_auth_failure(tmp_path: Path) -> None:
    provider = FakeProvider(
        outputs=[
            {
                "done": True,
                "actions": [
                    {
                        "name": "run_python_code",
                        "params": {"code": "raise RuntimeError('unauthorized: invalid api key')"},
                    }
                ],
                "final_output": "done",
            }
        ]
    )
    planner = Planner(provider=provider, model="m")
    settings = Settings(workspace=tmp_path, runs_dir=tmp_path / "runs", skills_dir=tmp_path)
    store = FilesystemStore(settings.runs_dir)
    runner = AgentLoopRunner(settings=settings, planner=planner, store=store)

    state = runner.start_run(
        task="เรียก API ภายนอกแล้วบันทึกผล",
        provider_name="openai",
        model="m",
        workspace=tmp_path,
        skills_dir=tmp_path,
        max_iters=1,
    )

    assert state.status == RunStatus.FAILED
    assert "[auto-escalation]" in state.last_output
