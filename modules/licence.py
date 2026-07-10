"""
modules/licence.py  —  Data Wrangler Licence Validation
=========================================================
Checks licence key validity on startup.

- First launch : prompts for key, validates against GitHub, saves locally
- Daily        : re-validates against GitHub (once per calendar day)
- Offline      : uses locally cached validation if GitHub unreachable
- Expired      : blocks with a message

Local state stored in: licence.json (app root, gitignored)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Load .env from app root before reading any env vars
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
_GITHUB_TOKEN = os.getenv("LICENCE_GITHUB_TOKEN", "")
_GITHUB_REPO  = os.getenv("LICENCE_GITHUB_REPO",  "perrystokes00/dw-licences")
_GITHUB_FILE  = "licences.json"
_SECRET       = os.getenv("LICENCE_SECRET", "dw-secret-change-me")
_LOCAL_FILE   = Path(__file__).parent.parent / "licence.json"
_TIMEOUT      = 8   # seconds


# ── Key validation (HMAC checksum) ────────────────────────────────────────────

def _key_format_valid(key: str) -> bool:
    """Check DW-XXXX-XXXX-XXXX-SIG format and HMAC signature."""
    parts = key.strip().upper().split("-")
    if len(parts) != 5 or parts[0] != "DW":
        return False
    raw = "-".join(parts[1:4])
    expected_sig = hmac.new(
        _SECRET.encode(), raw.encode(), hashlib.sha256
    ).hexdigest()[:4].upper()
    return parts[4] == expected_sig


# ── Local state ───────────────────────────────────────────────────────────────

def _load_local() -> dict:
    try:
        if _LOCAL_FILE.exists():
            return json.loads(_LOCAL_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_local(data: dict) -> None:
    try:
        _LOCAL_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# ── GitHub validation ─────────────────────────────────────────────────────────

def _fetch_licence_record(key: str) -> Optional[dict]:
    """
    Fetch the licence record for `key` from GitHub.
    Returns the record dict if found, None if not found or unreachable.
    """
    try:
        import base64
        url = (f"https://api.github.com/repos/{_GITHUB_REPO}"
               f"/contents/{_GITHUB_FILE}")
        headers = {
            "Authorization": f"token {_GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        r = requests.get(url, headers=headers, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        licences = json.loads(base64.b64decode(r.json()["content"]).decode())
        return licences.get(key.strip().upper())
    except Exception:
        return None


# ── Core check ────────────────────────────────────────────────────────────────

class LicenceResult:
    def __init__(self, valid: bool, message: str,
                 days_remaining: int = 0, customer: str = ""):
        self.valid          = valid
        self.message        = message
        self.days_remaining = days_remaining
        self.customer       = customer


def validate_licence(key: str) -> LicenceResult:
    """
    Full validation: format check → GitHub check → expiry check.
    Called on first activation and once per day thereafter.
    """
    key = key.strip().upper()

    # 1. Format check
    if not _key_format_valid(key):
        return LicenceResult(False, "Invalid licence key format.")

    # 2. GitHub check
    record = _fetch_licence_record(key)
    if record is None:
        return LicenceResult(
            False,
            "Could not validate licence. Check your internet connection and try again."
        )
    if not record.get("active", False):
        return LicenceResult(
            False,
            "This licence key has been revoked. Please contact the Data Wrangler team."
        )

    trial_days = int(record.get("trial_days", 30))
    customer   = record.get("customer", "")
    return LicenceResult(True, "Valid", trial_days, customer)


def check_expiry(first_run: str, trial_days: int) -> tuple[bool, int]:
    """
    Returns (still_valid, days_remaining) based on first_run date.
    first_run is ISO format YYYY-MM-DD.
    """
    try:
        start   = date.fromisoformat(first_run)
        elapsed = (date.today() - start).days
        remaining = trial_days - elapsed
        return remaining > 0, max(0, remaining)
    except Exception:
        return False, 0


# ── Main entry point ──────────────────────────────────────────────────────────

def get_licence_status() -> LicenceResult:
    """
    Called on every app launch.

    Returns LicenceResult with valid=True if the app should proceed,
    or valid=False with a message to display.
    """
    local = _load_local()
    today = date.today().isoformat()

    # ── Case 1: No local licence at all → needs activation ───────────────────
    if not local.get("key"):
        return LicenceResult(False, "NO_KEY")

    key        = local["key"]
    first_run  = local.get("first_run", today)
    trial_days = local.get("trial_days", 30)
    customer   = local.get("customer", "")
    last_check = local.get("last_check", "")

    # ── Case 2: Check expiry locally (fast, no network) ──────────────────────
    valid, days_remaining = check_expiry(first_run, trial_days)
    if not valid:
        return LicenceResult(
            False,
            f"Your {trial_days}-day trial expired. "
            f"Please contact the Data Wrangler team to purchase a licence.",
            0, customer
        )

    # ── Case 3: Re-validate against GitHub once per day ──────────────────────
    if last_check != today:
        result = validate_licence(key)
        if not result.valid:
            # GitHub says invalid/revoked — block
            return result
        # Update local cache with latest trial_days from server
        local["trial_days"] = result.days_remaining
        local["last_check"] = today
        _save_local(local)
        trial_days    = result.days_remaining
        days_remaining = days_remaining  # recalculate
        _, days_remaining = check_expiry(first_run, trial_days)

    return LicenceResult(True, "Valid", days_remaining, customer)


def activate_licence(key: str) -> LicenceResult:
    """
    Called when user submits a key for the first time.
    Validates against GitHub and saves locally if valid.
    """
    result = validate_licence(key)
    if not result.valid:
        return result

    # Save activation record
    local = {
        "key":        key.strip().upper(),
        "first_run":  date.today().isoformat(),
        "trial_days": result.days_remaining,
        "customer":   result.customer,
        "last_check": date.today().isoformat(),
        "activated":  datetime.utcnow().isoformat(),
    }
    _save_local(local)
    return result
