"""
generate_licence.py  —  Data Wrangler Licence Key Generator
============================================================
Run this privately to generate keys and update licences.json on GitHub.

Usage:
    python generate_licence.py --customer "Acme Corp" --days 30
    python generate_licence.py --customer "Acme Corp" --days 30 --push

Requires:
    pip install requests
    GITHUB_TOKEN, GITHUB_REPO set in environment or .env
"""

import argparse
import hashlib
import hmac
import json
import os
import random
import string
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("LICENCE_GITHUB_TOKEN")
GITHUB_REPO  = os.getenv("LICENCE_GITHUB_REPO", "perrystokes00/dw-licences")
GITHUB_FILE  = "licences.json"
SECRET       = os.getenv("LICENCE_SECRET", "dw-secret-change-me")


# ── Key generation ────────────────────────────────────────────────────────────

def generate_key() -> str:
    """Generate a DW-XXXX-XXXX-XXXX style key."""
    chars = string.ascii_uppercase + string.digits
    segments = ["".join(random.choices(chars, k=4)) for _ in range(3)]
    raw = "-".join(segments)
    # Append a short HMAC checksum so keys can't be guessed
    sig = hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()[:4].upper()
    return f"DW-{raw}-{sig}"


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def fetch_licences() -> tuple[dict, str]:
    """Fetch licences.json from GitHub. Returns (data, sha)."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    r = requests.get(url, headers=_headers(), timeout=10)
    if r.status_code == 404:
        return {}, ""
    r.raise_for_status()
    import base64
    data = json.loads(base64.b64decode(r.json()["content"]).decode())
    sha  = r.json()["sha"]
    return data, sha


def push_licences(data: dict, sha: str, message: str) -> None:
    """Push updated licences.json to GitHub."""
    import base64
    url     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    content = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
    payload = {"message": message, "content": content}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=_headers(), json=payload, timeout=10)
    r.raise_for_status()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_add(customer: str, days: int, push: bool) -> None:
    key = generate_key()
    entry = {
        "customer":   customer,
        "trial_days": days,
        "active":     True,
        "created":    datetime.utcnow().strftime("%Y-%m-%d"),
        "notes":      "",
    }
    print(f"\nGenerated key: {key}")
    print(f"Customer     : {customer}")
    print(f"Trial days   : {days}")

    if push:
        if not GITHUB_TOKEN:
            print("\nERROR: LICENCE_GITHUB_TOKEN not set in .env")
            sys.exit(1)
        print("\nFetching current licences from GitHub...")
        data, sha = fetch_licences()
        data[key] = entry
        push_licences(data, sha, f"Add licence for {customer}")
        print(f"Pushed — {len(data)} total licences in repo.")
    else:
        print("\nAdd this manually to licences.json:")
        print(json.dumps({key: entry}, indent=2))


def cmd_revoke(key: str) -> None:
    if not GITHUB_TOKEN:
        print("ERROR: LICENCE_GITHUB_TOKEN not set in .env")
        sys.exit(1)
    data, sha = fetch_licences()
    if key not in data:
        print(f"Key not found: {key}")
        sys.exit(1)
    data[key]["active"] = False
    push_licences(data, sha, f"Revoke licence {key}")
    print(f"Revoked: {key}")


def cmd_extend(key: str, days: int) -> None:
    if not GITHUB_TOKEN:
        print("ERROR: LICENCE_GITHUB_TOKEN not set in .env")
        sys.exit(1)
    data, sha = fetch_licences()
    if key not in data:
        print(f"Key not found: {key}")
        sys.exit(1)
    old_days = data[key].get("trial_days", 30)
    data[key]["trial_days"] = days
    data[key]["active"]     = True   # re-activate if previously revoked/expired
    data[key]["extended"]   = datetime.utcnow().strftime("%Y-%m-%d")
    push_licences(data, sha, f"Extend licence {key} to {days} days")
    print(f"Extended: {key}")
    print(f"  Customer : {data[key].get('customer', '')}")
    print(f"  Days     : {old_days} → {days}")
    print(f"\nThe app will pick up the new expiry on its next daily GitHub check.")
    print(f"No action needed from the user.")


def cmd_list() -> None:
    if not GITHUB_TOKEN:
        print("ERROR: LICENCE_GITHUB_TOKEN not set in .env")
        sys.exit(1)
    data, _ = fetch_licences()
    if not data:
        print("No licences found.")
        return
    print(f"\n{'Key':<25} {'Customer':<25} {'Days':>5} {'Active':>7} {'Created':>12} {'Extended':>12}")
    print("-" * 95)
    for k, v in data.items():
        print(f"{k:<25} {v.get('customer',''):<25} {v.get('trial_days',30):>5} "
              f"{'YES' if v.get('active') else 'NO':>7} {v.get('created',''):>12} "
              f"{v.get('extended',''):>12}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Data Wrangler Licence Manager")
    sub = parser.add_subparsers(dest="cmd")

    # add
    p_add = sub.add_parser("add", help="Generate and add a new licence key")
    p_add.add_argument("--customer", required=True, help="Customer name")
    p_add.add_argument("--days", type=int, default=30, help="Trial duration in days")
    p_add.add_argument("--push", action="store_true", help="Push directly to GitHub")

    # revoke
    p_rev = sub.add_parser("revoke", help="Revoke a licence key")
    p_rev.add_argument("key", help="Key to revoke")

    # extend
    p_ext = sub.add_parser("extend", help="Extend a licence to a new duration")
    p_ext.add_argument("key", help="Key to extend")
    p_ext.add_argument("--days", type=int, default=365, help="New total duration in days (default 365)")

    # list
    sub.add_parser("list", help="List all licences")

    args = parser.parse_args()

    if args.cmd == "add":
        cmd_add(args.customer, args.days, args.push)
    elif args.cmd == "revoke":
        cmd_revoke(args.key)
    elif args.cmd == "extend":
        cmd_extend(args.key, args.days)
    elif args.cmd == "list":
        cmd_list()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
