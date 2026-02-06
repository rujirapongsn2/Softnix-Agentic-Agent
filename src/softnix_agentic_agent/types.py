from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StopReason(str, Enum):
    COMPLETED = "completed"
    MAX_ITERS = "max_iters"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    CANCELED = "canceled"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class LLMResponse:
    content: str
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ProviderStatus:
    ok: bool
    message: str


@dataclass
class ActionResult:
    name: str
    ok: bool
    output: str
    error: str | None = None


@dataclass
class IterationRecord:
    run_id: str
    iteration: int
    timestamp: str
    prompt: str
    plan: dict[str, Any]
    actions: list[dict[str, Any]]
    action_results: list[dict[str, Any]]
    output: str
    done: bool
    error: str | None = None
    token_usage: dict[str, int] = field(default_factory=dict)


@dataclass
class RunState:
    run_id: str
    task: str
    provider: str
    model: str
    workspace: str
    skills_dir: str
    max_iters: int
    iteration: int = 0
    status: RunStatus = RunStatus.RUNNING
    stop_reason: StopReason | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_output: str = ""
    cancel_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task": self.task,
            "provider": self.provider,
            "model": self.model,
            "workspace": self.workspace,
            "skills_dir": self.skills_dir,
            "max_iters": self.max_iters,
            "iteration": self.iteration,
            "status": self.status.value,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_output": self.last_output,
            "cancel_requested": self.cancel_requested,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        return cls(
            run_id=data["run_id"],
            task=data["task"],
            provider=data["provider"],
            model=data["model"],
            workspace=data["workspace"],
            skills_dir=data["skills_dir"],
            max_iters=int(data["max_iters"]),
            iteration=int(data.get("iteration", 0)),
            status=RunStatus(data.get("status", RunStatus.RUNNING.value)),
            stop_reason=StopReason(data["stop_reason"]) if data.get("stop_reason") else None,
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
            last_output=data.get("last_output", ""),
            cancel_requested=bool(data.get("cancel_requested", False)),
        )
