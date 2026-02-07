from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time

import typer
import uvicorn

from softnix_agentic_agent.config import load_settings
from softnix_agentic_agent.providers.factory import create_provider
from softnix_agentic_agent.runtime import build_runner
from softnix_agentic_agent.skills.loader import SkillLoader

app = typer.Typer(help="Softnix Agentic Agent CLI")
skills_app = typer.Typer(help="Skills management")
api_app = typer.Typer(help="Local REST API")
app.add_typer(skills_app, name="skills")
app.add_typer(api_app, name="api")


@app.command("run")
def run(
    task: str = typer.Option(..., "--task", help="Task to execute"),
    provider: str | None = typer.Option(None, "--provider", help="openai|claude|custom"),
    model: str | None = typer.Option(None, "--model", help="Model name"),
    max_iters: int | None = typer.Option(None, "--max-iters", min=1),
    workspace: Path | None = typer.Option(None, "--workspace"),
    skills_dir: Path | None = typer.Option(None, "--skills-dir"),
) -> None:
    settings = load_settings()
    if _should_use_stdout_mode(workspace):
        resolved = _resolve_run_options(settings, provider, model, max_iters, workspace, skills_dir)
        output = _run_with_spinner(
            "Generating output",
            lambda: _run_stdout_mode(
                task=task,
                provider_name=resolved["provider"],
                model=resolved["model"],
                settings=settings,
            ),
        )
        typer.echo(output)
        return

    resolved = _resolve_run_options(settings, provider, model, max_iters, workspace, skills_dir)
    runner = build_runner(settings, provider_name=resolved["provider"], model=resolved["model"])
    state = _run_with_spinner(
        "Running agent",
        lambda: runner.start_run(
            task=task,
            provider_name=resolved["provider"],
            model=resolved["model"],
            workspace=resolved["workspace"],
            skills_dir=resolved["skills_dir"],
            max_iters=resolved["max_iters"],
        ),
    )
    typer.echo(f"run_id={state.run_id}")
    typer.echo(f"status={state.status.value}")
    typer.echo(f"stop_reason={state.stop_reason.value if state.stop_reason else 'n/a'}")
    if state.last_output:
        typer.echo("--- last_output ---")
        typer.echo(state.last_output)


@app.command("resume")
def resume(run_id: str = typer.Option(..., "--run-id")) -> None:
    settings = load_settings()
    try:
        # provider/model from state; provider argument is only needed for initial provider wiring.
        from softnix_agentic_agent.storage.filesystem_store import FilesystemStore

        store = FilesystemStore(settings.runs_dir)
        state = store.read_state(run_id)
        runner = build_runner(settings, provider_name=state.provider, model=state.model)
        new_state = runner.resume_run(run_id)
        typer.echo(f"run_id={new_state.run_id}")
        typer.echo(f"status={new_state.status.value}")
        typer.echo(f"stop_reason={new_state.stop_reason.value if new_state.stop_reason else 'n/a'}")
    except FileNotFoundError:
        raise typer.BadParameter(f"run_id not found: {run_id}")


@skills_app.command("list")
def list_skills(path: Path = typer.Option(Path("skillpacks"), "--path")) -> None:
    loader = SkillLoader(path)
    skills = loader.list_skills()
    if not skills:
        typer.echo("No skills found")
        return
    for skill in skills:
        typer.echo(f"- {skill.name}: {skill.description}")
        if skill.references:
            typer.echo(f"  refs: {', '.join(str(r) for r in skill.references[:3])}")


@api_app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
) -> None:
    uvicorn.run("softnix_agentic_agent.api.app:app", host=host, port=port, reload=False)


def _resolve_run_options(
    settings,
    provider: str | None,
    model: str | None,
    max_iters: int | None,
    workspace: Path | None,
    skills_dir: Path | None,
) -> dict:
    return {
        "provider": provider or settings.provider,
        "model": model or settings.model,
        "max_iters": max_iters or settings.max_iters,
        "workspace": workspace or settings.workspace,
        "skills_dir": skills_dir or settings.skills_dir,
    }


def _should_use_stdout_mode(workspace: Path | None) -> bool:
    if workspace is not None:
        return False
    configured_workspace = os.getenv("SOFTNIX_WORKSPACE", "").strip()
    return configured_workspace == ""


def _run_stdout_mode(task: str, provider_name: str, model: str, settings) -> str:
    provider = create_provider(provider_name, settings)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a coding assistant. Return only the final output content for the user's request. "
                "Do not return JSON, markdown fences, or tool/action plans."
            ),
        },
        {"role": "user", "content": task},
    ]
    response = provider.generate(messages=messages, model=model, max_tokens=4096)
    return response.content.strip()


def _run_with_spinner(label: str, fn):
    done = threading.Event()
    result = {}
    error = {}

    def worker() -> None:
        try:
            result["value"] = fn()
        except Exception as exc:  # pragma: no cover
            error["value"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    frames = ["|", "/", "-", "\\"]
    i = 0
    while not done.is_set():
        sys.stdout.write(f"\r{label}... {frames[i % len(frames)]}")
        sys.stdout.flush()
        i += 1
        time.sleep(0.1)

    thread.join()
    sys.stdout.write(f"\r{label}... done\n")
    sys.stdout.flush()

    if "value" in error:
        raise error["value"]
    return result["value"]


if __name__ == "__main__":
    app()
