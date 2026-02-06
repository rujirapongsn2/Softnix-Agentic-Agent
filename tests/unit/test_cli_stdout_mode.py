from pathlib import Path

from softnix_agentic_agent.cli import _run_stdout_mode
from softnix_agentic_agent.config import Settings


class _FakeProvider:
    def generate(self, messages, model, tools=None, temperature=0.2, max_tokens=1024):  # type: ignore[no-untyped-def]
        class _Resp:
            content = "<html>Hello</html>"

        return _Resp()


def test_run_stdout_mode(monkeypatch) -> None:
    from softnix_agentic_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "create_provider", lambda provider_name, settings: _FakeProvider())

    out = _run_stdout_mode(
        task="Write HTML",
        provider_name="claude",
        model="claude-haiku-4-5",
        settings=Settings(workspace=Path(".")),
    )
    assert out == "<html>Hello</html>"
