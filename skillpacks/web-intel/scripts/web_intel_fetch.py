#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

def _decide_web_fallback(
    extracted_text: str,
    *,
    task_hint: str = "",
    min_chars: int = 1200,
    required_keywords: list[str] | None = None,
) -> dict:
    text = (extracted_text or "").strip()
    reasons: list[str] = []
    matched: list[str] = []
    if len(text) < int(min_chars):
        reasons.append(f"content_too_short:{len(text)}<{int(min_chars)}")

    candidates: list[str] = []
    if required_keywords:
        candidates.extend([x.strip() for x in required_keywords if x.strip()])
    else:
        for tok in re.findall(r"[A-Za-z0-9ก-๙_-]{4,}", task_hint or ""):
            low = tok.lower()
            if low in {"http", "https", "www", "news", "summary", "สรุป"}:
                continue
            candidates.append(tok)

    uniq_keywords: list[str] = []
    seen = set()
    for kw in candidates:
        lk = kw.lower()
        if lk in seen:
            continue
        seen.add(lk)
        uniq_keywords.append(kw)
        if len(uniq_keywords) >= 8:
            break

    low_text = text.lower()
    for kw in uniq_keywords:
        if kw.lower() in low_text:
            matched.append(kw)
    if uniq_keywords and not matched:
        reasons.append("required_keywords_missing")

    return {
        "sufficient": len(reasons) == 0,
        "reasons": reasons,
        "content_length": len(text),
        "matched_keywords": matched,
        "required_keywords": uniq_keywords,
    }


def _clean_html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_html(url: str, timeout_sec: int) -> str:
    req = Request(
        url=url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
            )
        },
    )
    with urlopen(req, timeout=timeout_sec) as resp:  # nosec B310 - intended URL fetch adapter
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_browser_template(template: str, *, url: str, out_dir: Path, task_hint: str) -> tuple[bool, str]:
    cmd = (
        template.replace("{url}", url)
        .replace("{out_dir}", str(out_dir))
        .replace("{task_hint}", task_hint)
    )
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # nosec B602 - explicit operator template
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip()
    err = (proc.stderr or proc.stdout or f"exit_code={proc.returncode}").strip()
    return False, err


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch-first web intelligence adapter")
    parser.add_argument("--url", required=True, help="Target http/https URL")
    parser.add_argument("--task-hint", default="", help="Task hint for quality gate")
    parser.add_argument("--out-dir", default="web_intel", help="Output directory under workspace")
    parser.add_argument("--min-chars", type=int, default=1200, help="Minimum text chars before fallback")
    parser.add_argument(
        "--required-keywords",
        default="",
        help="Comma-separated keywords that should appear in extracted text",
    )
    parser.add_argument("--timeout-sec", type=int, default=20, help="Fetch timeout seconds")
    parser.add_argument(
        "--attempt-browser-fallback",
        action="store_true",
        help="Attempt browser command via SOFTNIX_WEB_INTEL_BROWSER_CMD_TEMPLATE when fetch is insufficient",
    )
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if parsed.scheme not in {"http", "https"}:
        print("error=invalid_url_scheme", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw.html"
    text_path = out_dir / "extracted.txt"
    summary_path = out_dir / "summary.md"
    meta_path = out_dir / "meta.json"

    meta: dict = {
        "generated_by": "web_intel_fetch.py",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "task_hint": args.task_hint,
        "mode": "web_fetch",
        "fallback_required": False,
        "fallback_attempted": False,
        "fallback_reason": "",
        "browser_command_used": "",
    }

    try:
        html = _fetch_html(args.url, timeout_sec=max(1, args.timeout_sec))
    except Exception as exc:
        meta.update({"status": "fetch_error", "error": str(exc)})
        _write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
        _write(summary_path, f"# Web Intel Summary\n\n- status: fetch_error\n- error: {exc}\n")
        print(f"error=fetch_failed {exc}", file=sys.stderr)
        return 1

    _write(raw_path, html)
    extracted = _clean_html_to_text(html)
    _write(text_path, extracted)

    required_keywords = [x.strip() for x in args.required_keywords.split(",") if x.strip()]
    decision = _decide_web_fallback(
        extracted,
        task_hint=args.task_hint,
        min_chars=max(1, int(args.min_chars)),
        required_keywords=required_keywords,
    )
    meta["quality_gate"] = decision

    if bool(decision["sufficient"]):
        meta["status"] = "ok"
        _write(
            summary_path,
            (
                "# Web Intel Summary\n\n"
                "- mode: web_fetch\n"
                "- quality: sufficient\n"
                f"- content_length: {decision['content_length']}\n\n"
                "## Preview\n\n"
                f"{extracted[:1000]}\n"
            ),
        )
        _write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    # Fallback required
    meta["fallback_required"] = True
    meta["fallback_reason"] = ";".join(decision["reasons"])
    template = os.getenv("SOFTNIX_WEB_INTEL_BROWSER_CMD_TEMPLATE", "").strip()
    meta["browser_command_used"] = template

    if args.attempt_browser_fallback and template:
        meta["fallback_attempted"] = True
        ok, detail = _run_browser_template(template, url=args.url, out_dir=out_dir, task_hint=args.task_hint)
        meta["mode"] = "browser_fallback"
        if ok:
            meta["status"] = "ok"
            _write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
            _write(
                summary_path,
                (
                    "# Web Intel Summary\n\n"
                    "- mode: browser_fallback\n"
                    "- quality: fallback_used\n"
                    f"- reason: {meta['fallback_reason']}\n"
                ),
            )
            return 0
        meta["status"] = "browser_fallback_failed"
        meta["error"] = detail
        _write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
        _write(
            summary_path,
            (
                "# Web Intel Summary\n\n"
                "- mode: browser_fallback\n"
                "- status: failed\n"
                f"- reason: {meta['fallback_reason']}\n"
                f"- error: {detail}\n"
            ),
        )
        print(f"error=browser_fallback_failed {detail}", file=sys.stderr)
        # Soft-fail: outputs are still produced, caller can continue with degraded summary.
        return 0

    meta["status"] = "fallback_required"
    _write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2))
    _write(
        summary_path,
        (
            "# Web Intel Summary\n\n"
            "- mode: web_fetch\n"
            "- quality: insufficient\n"
            f"- fallback_reason: {meta['fallback_reason']}\n"
            "- note: browser fallback required but not executed\n"
        ),
    )
    print("fallback_required=true", file=sys.stderr)
    # Soft-fail: keep automation moving; downstream should read meta.json status.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
