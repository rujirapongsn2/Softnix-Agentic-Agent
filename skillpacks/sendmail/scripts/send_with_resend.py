#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import sys
from typing import Mapping

import resend


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send email via Resend API")
    parser.add_argument("--from", dest="from_email", required=True, help='Sender, e.g. "Acme <onboarding@resend.dev>"')
    parser.add_argument("--to", required=True, help="Recipient(s), comma-separated")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--text", default="", help="Plain text body")
    parser.add_argument("--html", default="", help="HTML body")
    return parser.parse_args()


def resolve_api_key(env: Mapping[str, str], script_file: str) -> str:
    api_key = env.get("RESEND_API_KEY", "").strip()
    if api_key:
        return api_key

    key_file = env.get("RESEND_API_KEY_FILE", "").strip()
    if key_file:
        key_path = Path(key_file).expanduser()
    else:
        key_path = Path(script_file).resolve().parent.parent / ".secrets" / "RESEND_API_KEY"
    if key_path.exists() and key_path.is_file():
        return key_path.read_text(encoding="utf-8").strip()
    return ""


def build_payload(args: argparse.Namespace) -> resend.Emails.SendParams:
    recipients = [item.strip() for item in args.to.split(",") if item.strip()]
    text = args.text.strip()
    html = args.html.strip()

    if not recipients:
        raise ValueError("at least one recipient is required")
    if not text and not html:
        raise ValueError("provide at least one body (--text or --html)")

    payload: resend.Emails.SendParams = {
        "from": args.from_email.strip(),
        "to": recipients,
        "subject": args.subject.strip(),
    }
    if text:
        payload["text"] = text
    if html:
        payload["html"] = html
    return payload


def main() -> int:
    args = parse_args()

    api_key = resolve_api_key(os.environ, __file__)
    if not api_key:
        print(
            "error: RESEND_API_KEY is not set "
            "(or missing skill file: skillpacks/sendmail/.secrets/RESEND_API_KEY)",
            file=sys.stderr,
        )
        return 2

    try:
        payload = build_payload(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    resend.api_key = api_key

    try:
        result = resend.Emails.send(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
