from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from softnix_agentic_agent.skills.parser import parse_skill_file

SKILL_TEMPLATE_MARKER = "SOFTNIX_SKILL_TEMPLATE_V1"
SECRET_PLACEHOLDER = "__SET_ME__"


@dataclass
class SkillCreateRequest:
    skills_root: Path
    name: str
    description: str
    guidance: str = ""
    api_key_name: str = ""
    api_key_value: str = ""
    endpoint_template: str = "/orders/{item_id}"
    force: bool = False


@dataclass
class SkillCreateResult:
    skill_name: str
    skill_dir: Path
    created_files: list[Path]
    warnings: list[str]


@dataclass
class SkillValidationResult:
    skill_dir: Path
    ok: bool
    ready: bool
    errors: list[str]
    warnings: list[str]
    checks: list[str]


def normalize_skill_name(name: str) -> str:
    raw = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError("skill name is empty after normalization")
    return slug[:63]


def normalize_api_key_name(value: str) -> str:
    text = (value or "").strip().upper()
    if not text:
        return ""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", text):
        raise ValueError("api key name must match pattern [A-Z][A-Z0-9_]{1,63}")
    return text


def create_skill_scaffold(request: SkillCreateRequest) -> SkillCreateResult:
    skill_name = normalize_skill_name(request.name)
    api_key_name = normalize_api_key_name(request.api_key_name)
    description = (request.description or "").strip() or f"{skill_name} skill"
    endpoint_template = (request.endpoint_template or "").strip() or "/orders/{item_id}"

    root = request.skills_root.resolve()
    skill_dir = (root / skill_name).resolve()
    if skill_dir.exists() and not request.force:
        raise FileExistsError(f"skill already exists: {skill_dir}")

    script_rel = "scripts/check_status.py"
    script_file = skill_dir / script_rel
    skill_md = skill_dir / "SKILL.md"
    reference_file = skill_dir / "references" / "NOTES.md"
    secret_file = skill_dir / ".secret" / api_key_name if api_key_name else None
    created_files: list[Path] = []
    warnings: list[str] = []

    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / ".secret").mkdir(parents=True, exist_ok=True)

    skill_md.write_text(
        _build_skill_markdown(
            skill_name=skill_name,
            description=description,
            script_rel=script_rel,
            api_key_name=api_key_name,
        ),
        encoding="utf-8",
    )
    created_files.append(skill_md)

    script_file.write_text(
        _build_script_template(
            marker=SKILL_TEMPLATE_MARKER,
            skill_name=skill_name,
            api_key_name=api_key_name,
            endpoint_template=endpoint_template,
        ),
        encoding="utf-8",
    )
    created_files.append(script_file)

    reference_file.write_text(
        _build_references_text(
            skill_name=skill_name,
            guidance=request.guidance,
            endpoint_template=endpoint_template,
            api_key_name=api_key_name,
        ),
        encoding="utf-8",
    )
    created_files.append(reference_file)

    if secret_file is not None:
        key_value = (request.api_key_value or "").strip()
        if key_value:
            secret_file.write_text(f"{key_value}\n", encoding="utf-8")
        else:
            secret_file.write_text(f"{SECRET_PLACEHOLDER}\n", encoding="utf-8")
            warnings.append(
                f"{secret_file.relative_to(root)} has placeholder value; update before production use"
            )
        created_files.append(secret_file)

    return SkillCreateResult(
        skill_name=skill_name,
        skill_dir=skill_dir,
        created_files=created_files,
        warnings=warnings,
    )


def validate_skill_dir(skill_dir: Path, run_smoke: bool = True) -> SkillValidationResult:
    root = skill_dir.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[str] = []
    ready = True

    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        errors.append("missing SKILL.md")
    else:
        try:
            parsed = parse_skill_file(skill_md)
            if not parsed.name.strip():
                errors.append("SKILL.md metadata name is empty")
            if not parsed.description.strip():
                errors.append("SKILL.md metadata description is empty")
            checks.append("skill_markdown_parsed")
        except Exception as exc:
            errors.append(f"SKILL.md parse failed: {exc}")

    legacy_secret_dir = root / ".secrets"
    if legacy_secret_dir.exists():
        errors.append("legacy .secrets folder detected; use .secret instead")

    scripts_dir = root / "scripts"
    script_files = sorted(scripts_dir.glob("*.py")) if scripts_dir.exists() else []
    if not script_files:
        errors.append("missing python script in scripts/")
    else:
        checks.append(f"script_count={len(script_files)}")

    for script in script_files:
        content = script.read_text(encoding="utf-8")
        try:
            compile(content, str(script), "exec")
            checks.append(f"compile_ok:{script.name}")
        except Exception as exc:
            errors.append(f"compile failed: {script.name}: {exc}")

        if run_smoke and SKILL_TEMPLATE_MARKER in content:
            smoke_file = root / ".softnix_smoke_test.json"
            cmd = [
                sys.executable,
                str(script),
                "--self-test",
                "--output",
                str(smoke_file),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                stdout = (proc.stdout or "").strip()
                errors.append(
                    f"smoke test failed: {script.name} exit={proc.returncode} "
                    f"stdout={stdout[:200]} stderr={stderr[:200]}"
                )
            elif not smoke_file.exists():
                errors.append(f"smoke test did not create output file: {script.name}")
            else:
                checks.append(f"smoke_ok:{script.name}")
                try:
                    smoke_file.unlink()
                except Exception:
                    pass

        key_name = _extract_api_key_name_from_script(content)
        if key_name:
            secret_path = root / ".secret" / key_name
            if not secret_path.exists():
                ready = False
                warnings.append(f"missing .secret/{key_name}")
            else:
                value = secret_path.read_text(encoding="utf-8").strip()
                if (not value) or (value == SECRET_PLACEHOLDER):
                    ready = False
                    warnings.append(f".secret/{key_name} is empty or placeholder")

    ok = len(errors) == 0
    if not ok:
        ready = False
    return SkillValidationResult(
        skill_dir=root,
        ok=ok,
        ready=ready,
        errors=errors,
        warnings=warnings,
        checks=checks,
    )


def validation_result_to_dict(result: SkillValidationResult) -> dict[str, Any]:
    return {
        "skill_dir": str(result.skill_dir),
        "ok": result.ok,
        "ready": result.ready,
        "errors": result.errors,
        "warnings": result.warnings,
        "checks": result.checks,
    }


def validation_result_to_json(result: SkillValidationResult) -> str:
    return json.dumps(validation_result_to_dict(result), ensure_ascii=False, indent=2)


def _extract_api_key_name_from_script(content: str) -> str:
    match = re.search(r'^API_KEY_ENV\s*=\s*"([^"]*)"', content, flags=re.MULTILINE)
    if not match:
        return ""
    return normalize_api_key_name(match.group(1))


def _build_skill_markdown(skill_name: str, description: str, script_rel: str, api_key_name: str) -> str:
    lines = [
        "---",
        f"name: {skill_name}",
        f"description: {description}",
        "---",
        "",
        f"# {skill_name}",
        "",
        "ใช้ skill นี้เมื่อต้องการเรียก API ภายนอกเพื่อดึงสถานะ/ข้อมูล แล้วสรุปผลให้ผู้ใช้",
        "",
        "## Workflow",
        "1. รับ identifier จากผู้ใช้ (เช่น order id)",
        f"2. รันสคริปต์ `{script_rel}` เพื่อดึงข้อมูลจาก API",
        "3. อ่านไฟล์ผลลัพธ์จาก workspace แล้วสรุปให้ผู้ใช้",
    ]
    if api_key_name:
        lines.extend(
            [
                "",
                "## Security model",
                f"- API key environment: `{api_key_name}`",
                f"- ไฟล์ secret: `.secret/{api_key_name}`",
                "- ห้าม hardcode key ในโค้ดหรือ prompt",
            ]
        )
    return "\n".join(lines) + "\n"


def _build_references_text(skill_name: str, guidance: str, endpoint_template: str, api_key_name: str) -> str:
    lines = [
        f"# {skill_name} implementation notes",
        "",
        f"- endpoint_template: `{endpoint_template}`",
    ]
    if api_key_name:
        lines.append(f"- api_key_name: `{api_key_name}`")
    else:
        lines.append("- api_key_name: (not required)")
    if guidance.strip():
        lines.extend(["", "## User guidance", guidance.strip()])
    return "\n".join(lines) + "\n"


def _build_script_template(
    marker: str,
    skill_name: str,
    api_key_name: str,
    endpoint_template: str,
) -> str:
    base_env = f"{skill_name.upper().replace('-', '_')}_BASE_URL"
    return f"""#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib import request as urllib_request
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError

{marker} = True
API_KEY_ENV = "{api_key_name}"
BASE_URL_ENV = "{base_env}"
DEFAULT_ENDPOINT_TEMPLATE = {endpoint_template!r}
SECRET_PLACEHOLDER = "{SECRET_PLACEHOLDER}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch status data from remote API")
    parser.add_argument("--item-id", default="sample-id", help="identifier, e.g. order id")
    parser.add_argument("--base-url", default=os.getenv(BASE_URL_ENV, ""), help=f"API base url (or env {{BASE_URL_ENV}})")
    parser.add_argument("--endpoint-template", default=DEFAULT_ENDPOINT_TEMPLATE, help="endpoint template e.g. /orders/{{item_id}}")
    parser.add_argument("--output", default="{skill_name}_result.json", help="output json path")
    parser.add_argument("--timeout-sec", type=int, default=30, help="request timeout in seconds")
    parser.add_argument("--self-test", action="store_true", help="run local smoke test without network")
    return parser.parse_args()


def resolve_api_key() -> str:
    if not API_KEY_ENV:
        return ""
    env_value = os.getenv(API_KEY_ENV, "").strip()
    if env_value:
        return env_value
    secret_path = Path(__file__).resolve().parents[1] / ".secret" / API_KEY_ENV
    if secret_path.exists() and secret_path.is_file():
        value = secret_path.read_text(encoding="utf-8").strip()
        if value and value != SECRET_PLACEHOLDER:
            return value
    raise RuntimeError(f"missing API key: set env {{API_KEY_ENV}} or file .secret/{{API_KEY_ENV}}")


def fetch_status(base_url: str, endpoint_template: str, item_id: str, timeout_sec: int, api_key: str) -> dict:
    if not base_url.strip():
        raise RuntimeError(f"missing --base-url (or env {{BASE_URL_ENV}})")
    endpoint = endpoint_template.format(item_id=item_id)
    url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))
    headers = {{"Accept": "application/json"}}
    if api_key:
        headers["Authorization"] = f"Bearer {{api_key}}"
    req = urllib_request.Request(url=url, headers=headers, method="GET")
    try:
        with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception:
                data = {{"raw_text": raw}}
            return {{"url": url, "status_code": int(getattr(resp, "status", 200)), "data": data}}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"HTTPError status={{exc.code}} body={{body[:400]}}") from exc
    except URLError as exc:
        raise RuntimeError(f"URLError: {{exc}}") from exc


def write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_self_test(output: str) -> int:
    sample = {{
        "self_test": True,
        "skill": "{skill_name}",
        "status": "ok",
    }}
    write_json(output, sample)
    print(f"self_test=ok output={{output}}")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test(args.output)

    api_key = resolve_api_key()
    payload = fetch_status(
        base_url=args.base_url,
        endpoint_template=args.endpoint_template,
        item_id=args.item_id,
        timeout_sec=max(1, int(args.timeout_sec)),
        api_key=api_key,
    )
    payload["item_id"] = args.item_id
    write_json(args.output, payload)
    print(f"output={{args.output}}")
    print(f"item_id={{args.item_id}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
