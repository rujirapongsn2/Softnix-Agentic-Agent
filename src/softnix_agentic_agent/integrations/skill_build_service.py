from __future__ import annotations

import shutil
import threading
from pathlib import Path
import re
from typing import Any

from softnix_agentic_agent.config import Settings
from softnix_agentic_agent.skills.factory import (
    SkillCreateRequest,
    create_skill_scaffold,
    normalize_skill_name,
    validate_skill_dir,
    validation_result_to_dict,
)
from softnix_agentic_agent.storage.skill_build_store import SkillBuildStore


class SkillBuildService:
    def __init__(self, settings: Settings, store: SkillBuildStore | None = None) -> None:
        self.settings = settings
        self.store = store or SkillBuildStore(settings.skill_builds_dir)
        self._threads: dict[str, threading.Thread] = {}

    def start_build(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = str(payload.get("task", "")).strip()
        if not task:
            raise ValueError("task is required")
        explicit_name = self._clean_text(payload.get("skill_name"))
        skill_name = normalize_skill_name(explicit_name) if explicit_name else self._infer_skill_name(task)
        api_key_name = self._clean_text(payload.get("api_key_name")).upper()
        api_key_value = self._clean_text(payload.get("api_key_value"))
        job = self.store.create_job(
            {
                "task": task,
                "skill_name": skill_name,
                "install_on_success": bool(payload.get("install_on_success", True)),
                "allow_overwrite": bool(payload.get("allow_overwrite", False)),
                "api_key_name": api_key_name,
                "api_key_provided": bool(api_key_value),
            }
        )
        self.store.append_event(job["id"], f"job created skill_name={skill_name}")
        thread = threading.Thread(
            target=self._run_build,
            args=(job["id"], payload, skill_name, api_key_name, api_key_value),
            daemon=True,
        )
        self._threads[job["id"]] = thread
        thread.start()
        return self.store.get_job(job["id"])

    def get_build(self, job_id: str) -> dict[str, Any]:
        return self.store.get_job(job_id)

    def list_builds(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_jobs(limit=limit)

    def read_events(self, job_id: str) -> list[str]:
        return self.store.read_events(job_id)

    def _run_build(
        self,
        job_id: str,
        payload: dict[str, Any],
        skill_name: str,
        api_key_name: str,
        api_key_value: str,
    ) -> None:
        try:
            self.store.update_job(job_id, {"status": "running", "stage": "staging"})
            build_root = self.store.build_dir(job_id)
            staging_root = self.store.staging_dir(job_id)
            staging_skills_root = staging_root / "skillpacks"
            staging_skills_root.mkdir(parents=True, exist_ok=True)
            self.store.append_event(job_id, f"staging initialized path={staging_root}")

            create_result = create_skill_scaffold(
                SkillCreateRequest(
                    skills_root=staging_skills_root,
                    name=skill_name,
                    description=self._clean_text(payload.get("description")),
                    guidance=self._clean_text(payload.get("guidance")),
                    api_key_name=api_key_name,
                    api_key_value=api_key_value,
                    endpoint_template=self._clean_text(payload.get("endpoint_template")) or "/orders/{item_id}",
                    force=True,
                )
            )
            self.store.append_event(
                job_id,
                f"scaffold generated files={len(create_result.created_files)} warnings={len(create_result.warnings)}",
            )

            self.store.update_job(job_id, {"stage": "validate"})
            validation = validate_skill_dir(create_result.skill_dir, run_smoke=True)
            validation_payload = validation_result_to_dict(validation)
            self.store.update_job(job_id, {"validation": validation_payload})
            if not validation.ok or not validation.ready:
                self.store.append_event(job_id, "validation failed; build stopped")
                self.store.update_job(
                    job_id,
                    {
                        "status": "failed",
                        "stage": "failed",
                        "error": self._validation_error_text(validation_payload),
                    },
                )
                return
            self.store.append_event(job_id, "validation passed")

            install_on_success = bool(payload.get("install_on_success", True))
            if not install_on_success:
                self.store.update_job(
                    job_id,
                    {
                        "status": "completed",
                        "stage": "completed",
                        "installed_path": str(create_result.skill_dir),
                    },
                )
                self.store.append_event(job_id, "install skipped by install_on_success=false")
                return

            self.store.update_job(job_id, {"stage": "install"})
            target_root = self.settings.skills_dir.resolve()
            target_root.mkdir(parents=True, exist_ok=True)
            target_dir = (target_root / skill_name).resolve()
            if target_dir.exists():
                if not bool(payload.get("allow_overwrite", False)):
                    self.store.update_job(
                        job_id,
                        {
                            "status": "failed",
                            "stage": "failed",
                            "error": f"skill already exists: {target_dir}",
                        },
                    )
                    self.store.append_event(job_id, "install failed: target exists and allow_overwrite=false")
                    return
                backup_root = build_root / "backup"
                backup_root.mkdir(parents=True, exist_ok=True)
                backup_dir = backup_root / skill_name
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                shutil.copytree(target_dir, backup_dir)
                shutil.rmtree(target_dir)
                self.store.append_event(job_id, f"backup created: {backup_dir}")

            shutil.copytree(create_result.skill_dir, target_dir)
            self.store.append_event(job_id, f"installed to {target_dir}")

            final_validation = validate_skill_dir(target_dir, run_smoke=True)
            final_payload = validation_result_to_dict(final_validation)
            self.store.update_job(job_id, {"validation": final_payload})
            if not final_validation.ok or not final_validation.ready:
                self.store.update_job(
                    job_id,
                    {
                        "status": "failed",
                        "stage": "failed",
                        "error": f"post-install validation failed: {self._validation_error_text(final_payload)}",
                        "installed_path": str(target_dir),
                    },
                )
                self.store.append_event(job_id, "post-install validation failed")
                return

            self.store.update_job(
                job_id,
                {
                    "status": "completed",
                    "stage": "completed",
                    "installed_path": str(target_dir),
                },
            )
            self.store.append_event(job_id, "build completed")
        except Exception as exc:
            self.store.update_job(
                job_id,
                {
                    "status": "failed",
                    "stage": "failed",
                    "error": str(exc),
                },
            )
            self.store.append_event(job_id, f"error: {exc}")

    def _validation_error_text(self, payload: dict[str, Any]) -> str:
        errors = [str(x) for x in payload.get("errors", []) if str(x).strip()]
        warnings = [str(x) for x in payload.get("warnings", []) if str(x).strip()]
        if errors:
            return "; ".join(errors[:3])
        if warnings:
            return "; ".join(warnings[:3])
        return "validation failed"

    def _infer_skill_name(self, task: str) -> str:
        text = (task or "").strip()
        lowered = text.lower()
        explicit = None
        m = re.search(r"skill\s+([a-z0-9][a-z0-9_-]{1,63})", lowered)
        if m:
            explicit = m.group(1)
        if explicit:
            return normalize_skill_name(explicit)
        if ("สถานะ" in text) and ("คำสั่งซื้อ" in text):
            return "order-status"
        try:
            base = normalize_skill_name(text)
        except ValueError:
            return "generated-skill"
        if len(base) < 4:
            return "generated-skill"
        return base[:32]

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()
