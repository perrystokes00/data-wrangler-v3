"""
modules/seis_filename_parser.py
================================
Extract survey name, line name and UWI candidates from seismic filenames.

Rules:
  UWI candidate   — any sequence of 10+ digits (API number pattern)
  Survey name     — longest non-numeric, non-extension token (split on _ - . space)
  Line name       — token matching LINE/SL/XL/IL/CDP + number pattern
"""
from __future__ import annotations
import re
from pathlib import Path


# ── UWI extraction ────────────────────────────────────────────────────────────

_UWI_RE = re.compile(r'\b(\d{10,})\b')

def extract_uwi(filename: str) -> str:
    """Return first 10+-digit sequence found in filename, else empty string."""
    stem = Path(filename).stem
    m = _UWI_RE.search(stem)
    return m.group(1) if m else ""


# ── Survey / line name extraction ─────────────────────────────────────────────

_LINE_RE = re.compile(
    r'(?i)\b((?:LINE|SL|XL|IL|CDP|INLINE|XLINE|SHOT)[-_]?\d+)\b'
)

_SPLIT_RE = re.compile(r'[_\-\.\s]+')


def extract_line_name(filename: str) -> str:
    """Return first line-name token (LINE001, XL100 etc.) found, else empty."""
    stem = Path(filename).stem
    m = _LINE_RE.search(stem)
    return m.group(1).upper() if m else ""


def extract_survey_name(filename: str) -> str:
    """
    Return the longest non-numeric, non-extension token from the filename
    after removing UWI digits and line name tokens. This is the best
    guess at a survey name.
    """
    stem = Path(filename).stem

    # Remove UWI digits
    stem = _UWI_RE.sub("", stem)
    # Remove line tokens
    stem = _LINE_RE.sub("", stem)

    # Split on separators
    tokens = [t for t in _SPLIT_RE.split(stem) if t]

    # Keep only tokens that aren't purely numeric and are >= 2 chars
    words = [t.upper() for t in tokens
             if t and not t.isdigit() and len(t) >= 2]

    if not words:
        return ""

    # Return longest token as survey name candidate,
    # or join all if they form a coherent name
    if len(words) == 1:
        return words[0]

    # If all words together form a reasonable name, join them
    joined = "_".join(words)
    return joined


def parse_seis_filename(filename: str) -> dict:
    """
    Parse a seismic filename and return all extracted components.

    Returns:
        {
            "uwi":         str — 10+-digit UWI candidate or ""
            "survey_name": str — survey name candidate or ""
            "line_name":   str — line name candidate (LINE001 etc.) or ""
        }
    """
    return {
        "uwi":         extract_uwi(filename),
        "survey_name": extract_survey_name(filename),
        "line_name":   extract_line_name(filename),
    }


def parse_seis_filenames(filenames: list[str]) -> list[dict]:
    """Parse a list of filenames. Returns list of dicts."""
    return [{"file_name": f, **parse_seis_filename(f)} for f in filenames]
