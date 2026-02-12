from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


def _resolve_api_key() -> str:
    env_key = os.getenv("TAVILY_API_KEY", "").strip()
    if env_key:
        return env_key

    # Script runs from .softnix_skill_exec/<skill>/scripts, so ../.secret works.
    secret_file = Path(__file__).resolve().parents[1] / ".secret" / "TAVILY_API_KEY"
    if secret_file.exists() and secret_file.is_file():
        return secret_file.read_text(encoding="utf-8").strip()

    raise RuntimeError("TAVILY_API_KEY is missing (env or .secret/TAVILY_API_KEY)")


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"HTTPError status={exc.code} body={body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"URLError: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Search web data via Tavily API")
    parser.add_argument("--query", required=True, help="search query")
    parser.add_argument("--max-results", type=int, default=5, help="max result entries")
    parser.add_argument("--output", default="tavily_result.json", help="output json path")
    parser.add_argument("--topic", default="general", help="Tavily topic: general/news")
    parser.add_argument("--search-depth", default="advanced", help="basic/advanced")
    args = parser.parse_args()

    api_key = _resolve_api_key()
    payload = {
        "api_key": api_key,
        "query": args.query,
        "topic": args.topic,
        "search_depth": args.search_depth,
        "max_results": max(1, min(int(args.max_results), 20)),
        "include_answer": True,
        "include_raw_content": False,
    }
    response = _post_json("https://api.tavily.com/search", payload)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

    count = len(response.get("results", []) or [])
    print(f"query={args.query}")
    print(f"results={count}")
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
