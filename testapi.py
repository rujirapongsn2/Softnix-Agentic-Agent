#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _request(method: str, url: str, payload: dict | None = None, timeout: float = 15.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            status = resp.getcode()
            return status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        return exc.code, body


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _json(body: str) -> dict:
    return json.loads(body) if body.strip() else {}


def run_tests(base_url: str, provider: str, model: str, workspace: str, skills_dir: str) -> int:
    failures = 0

    def check(name: str, fn):
        nonlocal failures
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {name}: {exc}")

    state = {"run_id": None}

    def test_create_run() -> None:
        status, body = _request(
            "POST",
            f"{base_url}/runs",
            {
                "task": "API feature test: create a small HTML file",
                "provider": provider,
                "model": model,
                "max_iters": 2,
                "workspace": workspace,
                "skills_dir": skills_dir,
            },
        )
        _expect(status == 200, f"expected 200, got {status}, body={body}")
        data = _json(body)
        _expect("run_id" in data, f"missing run_id in response: {body}")
        state["run_id"] = data["run_id"]

    def test_get_run() -> None:
        run_id = state["run_id"]
        _expect(run_id is not None, "run_id is None")
        time.sleep(1)
        status, body = _request("GET", f"{base_url}/runs/{run_id}")
        _expect(status == 200, f"expected 200, got {status}, body={body}")
        data = _json(body)
        _expect(data.get("run_id") == run_id, f"run_id mismatch: {body}")
        _expect("status" in data, f"missing status in: {body}")
        _expect("stop_reason" in data, f"missing stop_reason in: {body}")

    def test_get_iterations() -> None:
        run_id = state["run_id"]
        _expect(run_id is not None, "run_id is None")
        status, body = _request("GET", f"{base_url}/runs/{run_id}/iterations")
        _expect(status == 200, f"expected 200, got {status}, body={body}")
        data = _json(body)
        _expect("items" in data, f"missing items in: {body}")
        _expect(isinstance(data["items"], list), f"items is not list: {body}")

    def test_cancel_run() -> None:
        run_id = state["run_id"]
        _expect(run_id is not None, "run_id is None")
        status, body = _request("POST", f"{base_url}/runs/{run_id}/cancel")
        _expect(status == 200, f"expected 200, got {status}, body={body}")
        data = _json(body)
        _expect(data.get("status") == "cancel_requested", f"unexpected response: {body}")

    def test_get_missing_run() -> None:
        status, body = _request("GET", f"{base_url}/runs/not_found_run_id")
        _expect(status == 404, f"expected 404, got {status}, body={body}")

    def test_cancel_missing_run() -> None:
        status, body = _request("POST", f"{base_url}/runs/not_found_run_id/cancel")
        _expect(status == 404, f"expected 404, got {status}, body={body}")

    check("POST /runs", test_create_run)
    check("GET /runs/{id}", test_get_run)
    check("GET /runs/{id}/iterations", test_get_iterations)
    check("POST /runs/{id}/cancel", test_cancel_run)
    check("GET /runs/{id} (404)", test_get_missing_run)
    check("POST /runs/{id}/cancel (404)", test_cancel_missing_run)

    print("\n=== Summary ===")
    print(f"Base URL: {base_url}")
    print(f"Run ID: {state['run_id']}")
    print(f"Failures: {failures}")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Softnix API feature test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--provider", default="claude")
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--workspace", default="./tmp")
    parser.add_argument("--skills-dir", default="examples/skills")
    args = parser.parse_args()

    return run_tests(
        base_url=args.base_url.rstrip("/"),
        provider=args.provider,
        model=args.model,
        workspace=args.workspace,
        skills_dir=args.skills_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
