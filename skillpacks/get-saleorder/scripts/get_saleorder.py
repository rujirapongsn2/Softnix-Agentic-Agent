#!/usr/bin/env python
"""Softnix Sale Order Fetcher

Dึงข้อมูล Sale Order จาก Softnix API

Usage:
  python get_saleorder.py --days 7
  python get_saleorder.py --days 30
  python get_saleorder.py --start-date 2024-01-01 --end-date 2024-01-31
  python get_saleorder.py --days 7 --date-type payout
"""
import argparse
import json
import os
import sys
import requests

# --- Config ---
BASE_URL = "http://192.168.10.123:3000"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
SECRET_PATH = os.path.join(SKILL_DIR, ".secret", "SESSION_TOKEN")

# Output directory (workspace-relative)
OUT_DIR = os.environ.get("OUT_DIR", "get_saleorder")


def load_cookie():
    """Load session token from .secret file."""
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "r") as f:
            return f.read().strip()
    # Fallback: environment variable
    token = os.environ.get("SESSION_TOKEN", "")
    if token:
        return token
    print("WARNING: No session token found. Set SESSION_TOKEN env or create .secret/SESSION_TOKEN")
    return ""


def get_documents(params=None, cookie=None):
    """Fetch documents from Softnix API."""
    url = f"{BASE_URL}/api/documents"
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    print(f"GET {resp.url}")
    print(f"Status: {resp.status_code}")
    
    try:
        data = resp.json()
        if isinstance(data, list):
            print(f"Records: {len(data)}")
        return {"status": resp.status_code, "url": str(resp.url), "data": data}
    except Exception:
        text = resp.text[:2000]
        print(f"Response (non-JSON): {text[:200]}")
        return {"status": resp.status_code, "url": str(resp.url), "data": text}


def main():
    parser = argparse.ArgumentParser(description="Fetch Softnix Sale Orders")
    parser.add_argument("--days", type=int, help="Number of days to look back (e.g. 7, 30)")
    parser.add_argument("--start-date", dest="start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", dest="end_date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--date-type", dest="date_type", help="Date type filter (e.g. 'payout')")
    parser.add_argument("--out-dir", dest="out_dir", default=OUT_DIR, help="Output directory")
    args = parser.parse_args()

    # Build query params
    params = {}
    if args.days is not None:
        params["days"] = args.days
    if args.start_date:
        params["startDate"] = args.start_date
    if args.end_date:
        params["endDate"] = args.end_date
    if args.date_type:
        params["dateType"] = args.date_type

    if not params:
        # Default: last 7 days
        params["days"] = 7
        print("No parameters specified, defaulting to --days 7")

    cookie = load_cookie()
    result = get_documents(params=params, cookie=cookie)

    # Ensure output directory exists
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "resp.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\nResult saved to: {out_path}")
    print("-" * 60)

    # Summary
    if isinstance(result.get("data"), list):
        print(f"Total records: {len(result['data'])}")
        for i, rec in enumerate(result["data"][:5]):
            doc_no = rec.get("documentNo", rec.get("id", "N/A"))
            print(f"  [{i+1}] {doc_no}")
        if len(result["data"]) > 5:
            print(f"  ... and {len(result['data']) - 5} more")
    else:
        print(f"Response type: {type(result.get('data')).__name__}")


if __name__ == "__main__":
    main()
