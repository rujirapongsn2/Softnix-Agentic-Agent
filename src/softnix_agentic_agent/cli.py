from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from softnix_agentic_agent.config import load_settings
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
    provider: str = typer.Option("openai", "--provider", help="openai|claude|custom"),
    model: str | None = typer.Option(None, "--model", help="Model name"),
    max_iters: int = typer.Option(10, "--max-iters", min=1),
    workspace: Path = typer.Option(Path("."), "--workspace"),
    skills_dir: Path = typer.Option(Path("examples/skills"), "--skills-dir"),
) -> None:
    settings = load_settings()
    runner = build_runner(settings, provider_name=provider, model=model)
    state = runner.start_run(
        task=task,
        provider_name=provider,
        model=model or settings.model,
        workspace=workspace,
        skills_dir=skills_dir,
        max_iters=max_iters,
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
def list_skills(path: Path = typer.Option(Path("examples/skills"), "--path")) -> None:
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


if __name__ == "__main__":
    app()
