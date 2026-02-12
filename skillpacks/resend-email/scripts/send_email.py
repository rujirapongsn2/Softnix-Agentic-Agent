#!/usr/bin/env python
"""Send email via Resend API.

Usage:
    python send_email.py --to "a@b.com" --subject "Hi" --html "<b>Hello</b>" --out-dir resend_email

The API key is read from the .secret/RESEND_API_KEY file (relative to skill root).
"""

import argparse
import json
import os
from pathlib import Path
import sys


def load_api_key():
    """Load Resend API key from .secret file."""
    # Try multiple possible locations for the secret file
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", ".secret", "RESEND_API_KEY"),
        os.path.join(os.getcwd(), "skills", "resend-email", ".secret", "RESEND_API_KEY"),
        os.path.join(os.getcwd(), ".secret", "RESEND_API_KEY"),
    ]
    # Also check environment variable as fallback
    env_key = os.environ.get("RESEND_API_KEY")
    if env_key:
        return env_key.strip()

    for path in candidates:
        resolved = os.path.normpath(path)
        if os.path.isfile(resolved):
            with open(resolved, "r", encoding="utf-8") as f:
                return f.read().strip()

    print("ERROR: RESEND_API_KEY not found.")
    print("Place your key in skills/resend-email/.secret/RESEND_API_KEY")
    print("or set the RESEND_API_KEY environment variable.")
    sys.exit(1)


def resolve_sender(sender: str) -> str:
    value = (sender or "").strip()
    if value:
        return value
    env_sender = os.environ.get("RESEND_FROM_EMAIL", "").strip()
    if env_sender:
        return env_sender
    return "Acme <onboarding@resend.dev>"


def send_email(sender: str, to: list, subject: str, html: str):
    """Send an email using the Resend SDK."""
    try:
        import resend
    except ImportError:
        print("ERROR: 'resend' package not installed. Run: pip install resend")
        sys.exit(1)

    resend.api_key = load_api_key()

    params: resend.Emails.SendParams = {
        "from": resolve_sender(sender),
        "to": to,
        "subject": subject,
        "html": html,
    }

    try:
        response = resend.Emails.send(params)
        print(f"Email sent successfully! Response: {response}")
        return response
    except Exception as e:
        print(f"Error sending email: {e}")
        sys.exit(1)


def write_result(out_dir: str, payload: dict):
    root = Path(out_dir or "resend_email")
    root.mkdir(parents=True, exist_ok=True)
    target = root / "result.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"result saved: {target}")


def main():
    parser = argparse.ArgumentParser(description="Send email via Resend API")
    parser.add_argument("--from", dest="sender", required=False, default="", help="Sender address, e.g. 'Name <email@domain>'")
    parser.add_argument("--to", required=True, help="Recipient email(s), comma-separated")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--html", required=True, help="HTML body content")
    parser.add_argument("--out-dir", default="resend_email", help="Output directory for result JSON")
    args = parser.parse_args()

    recipients = [addr.strip() for addr in args.to.split(",") if addr.strip()]
    response = send_email(sender=args.sender, to=recipients, subject=args.subject, html=args.html)
    write_result(
        out_dir=args.out_dir,
        payload={
            "ok": True,
            "to": recipients,
            "subject": args.subject,
            "response": response,
        },
    )


if __name__ == "__main__":
    main()
