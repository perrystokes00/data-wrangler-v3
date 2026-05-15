"""
modules/lis_catalog.py
======================
LIS (Log Information Standard) file classifier and header extractor.

LIS is an older Schlumberger binary format predating DLIS. Files often
contain wellsite data records (type 0x00), tool string records (0x01),
and data format specification records (0x40). The format is notoriously
non-compliant in the wild, so this module uses dlisio's LIS reader as
the primary path and falls back to a raw byte scanner for files that
dlisio cannot open.

Returns a flat dict compatible with _extract_fields() in page_workbench.
"""
from __future__ import annotations
import re
import struct
from pathlib import Path
from typing import Optional


# ── LIS record type constants ─────────────────────────────────────────────────
_RT_WELLSITE   = 0x00   # Wellsite data
_RT_TOOL       = 0x01   # Tool string
_RT_DFSR       = 0x40   # Data Format Specification Record (curves defined here)
_RT_RECD       = 0x80   # Logical record type: Normal Data

# Max bytes to scan in fallback mode (first 256 KB)
_SCAN_BYTES = 256 * 1024


def _clean(val) -> Optional[str]:
    """Strip, drop empty / null-sentinel strings."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("", "none", "unknown", "--", "null") else None


# ══════════════════════════════════════════════════════════════════════════════
# Primary path — dlisio LIS reader
# ══════════════════════════════════════════════════════════════════════════════

def _via_dlisio(file_path: str) -> dict:
    """
    Use dlisio to open the LIS file and extract wellsite parameters.
    dlisio exposes LIS wellsite data as key/value pairs on each logical
    file, and DFSR records tell us the curve mnemonics.

    Returns a partial fields dict, or raises if dlisio cannot open it.
    """
    import dlisio

    fields: dict = {}
    curve_names: list = []
    n_frames = 0

    # dlisio.lis.load returns a tuple of logical files
    lf_tuple = dlisio.lis.load(file_path)
    logical_files = list(lf_tuple)

    for lf in logical_files:
        # ── Wellsite data ─────────────────────────────────────────────────────
        try:
            for wd in lf.wellsite_data():
                for block in wd.components():
                    mnem = _clean(getattr(block, "mnemonic", None)) or ""
                    val  = _clean(str(getattr(block, "value", "") or ""))
                    if not val:
                        continue
                    mu = mnem.upper()
                    if mu in ("WELL", "WN", "WELLNAME"):
                        fields.setdefault("well_name", val)
                    elif mu in ("UWI", "API", "APINUM"):
                        fields.setdefault("uwi", val)
                    elif mu in ("COMP", "COMPANY", "OPERATOR", "OP"):
                        fields.setdefault("operator", val)
                    elif mu in ("FLD", "FIELD", "FIELDNAME"):
                        fields.setdefault("well_field", val)
                    elif mu in ("STAT", "STATE"):
                        fields.setdefault("state", val)
                    elif mu in ("CNTY", "COUNTY"):
                        fields.setdefault("county", val)
                    elif mu in ("SRVC", "SERVICE", "CONTRACTOR"):
                        fields.setdefault("contractor", val)
                    elif mu in ("STRT", "START", "TOP"):
                        fields.setdefault("depth_start", val)
                    elif mu in ("STOP", "END", "TD", "BOTTOM"):
                        fields.setdefault("depth_stop", val)
        except Exception:
            pass

        # ── Curve names from DFSR ─────────────────────────────────────────────
        try:
            for dfsr in lf.data_format_specs():
                for ch in dfsr.specs:
                    mn = _clean(getattr(ch, "mnemonic", None))
                    if mn and mn.upper() not in ("DEPT", "DEPTH", "MD"):
                        curve_names.append(mn)
                n_frames += 1
        except Exception:
            pass

        # ── Frame count ───────────────────────────────────────────────────────
        try:
            for frame in lf.frames():
                n_frames += len(frame)
        except Exception:
            pass

    fields["curve_names"] = list(dict.fromkeys(curve_names))[:20]  # dedupe
    fields["n_curves"]    = len(fields["curve_names"])
    fields["n_frames"]    = n_frames

    # Build a human-readable description
    depth_range = ""
    if fields.get("depth_start") and fields.get("depth_stop"):
        depth_range = f" · {fields['depth_start']}–{fields['depth_stop']} ft"
    curves_str = ""
    if fields["curve_names"]:
        curves_str = " · Curves: " + ", ".join(fields["curve_names"][:6])

    fields["description"] = (
        f"LIS · {len(logical_files)} logical file(s)"
        f" · {fields['n_curves']} curve(s){depth_range}{curves_str}"
    )

    return fields


# ══════════════════════════════════════════════════════════════════════════════
# Fallback path — raw byte scanner
# ══════════════════════════════════════════════════════════════════════════════

# ASCII patterns for common wellsite mnemonics embedded in binary LIS files
_PATTERNS = {
    "well_name":  [rb"WELL[\s:=]+([A-Za-z0-9 #\-_/]{2,40})"],
    "uwi":        [rb"UWI[\s:=]+([0-9\-]{10,20})",
                   rb"API[\s:=]+([0-9\-]{10,14})"],
    "operator":   [rb"COMP[\s:=]+([A-Za-z0-9 &\-\.]{2,40})",
                   rb"OPERATOR[\s:=]+([A-Za-z0-9 &\-\.]{2,40})"],
    "well_field": [rb"FLD[\s:=]+([A-Za-z0-9 \-_]{2,40})",
                   rb"FIELD[\s:=]+([A-Za-z0-9 \-_]{2,40})"],
    "state":      [rb"STAT[\s:=]+([A-Za-z]{2,20})"],
    "county":     [rb"CNTY[\s:=]+([A-Za-z ]{2,30})",
                   rb"COUNTY[\s:=]+([A-Za-z ]{2,30})"],
}


def _via_raw_scan(file_path: str) -> dict:
    """
    Fallback: read the first _SCAN_BYTES of the file and apply regex
    patterns to ASCII-printable runs to extract wellsite metadata.
    Not as reliable as dlisio but handles corrupt / non-standard files.
    """
    fields: dict = {}

    try:
        with open(file_path, "rb") as fh:
            blob = fh.read(_SCAN_BYTES)
    except OSError:
        return fields

    # Replace non-printable bytes with spaces to make regex easier
    printable = bytes(
        b if 0x20 <= b < 0x7F or b in (0x09, 0x0A, 0x0D) else 0x20
        for b in blob
    )

    for field_key, patterns in _PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, printable, re.IGNORECASE)
            if m:
                val = _clean(m.group(1).decode("ascii", errors="replace"))
                if val:
                    fields[field_key] = val
                    break

    fields["description"] = "LIS · header extracted via byte scan (non-standard file)"
    fields["curve_names"] = []
    fields["n_curves"]    = 0
    fields["n_frames"]    = 0

    return fields


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def classify_lis(file_path: str) -> dict:
    """
    Extract metadata from a LIS file.

    Returns a flat dict with keys matching _extract_fields() in
    page_workbench.py:
        well_name, uwi, operator, well_field, state, county,
        contractor, depth_start, depth_stop, description,
        curve_names, n_curves, n_frames, confidence, error

    Tries dlisio first; falls back to raw byte scan on failure.
    """
    result = {
        "file_category": "WELL",
        "report_type":   "WELL_LOG",
        "well_name":     None,
        "uwi":           None,
        "operator":      None,
        "well_field":    None,
        "state":         None,
        "county":        None,
        "contractor":    None,
        "depth_start":   None,
        "depth_stop":    None,
        "description":   "LIS — no metadata extracted",
        "curve_names":   [],
        "n_curves":      0,
        "n_frames":      0,
        "confidence":    0.0,
        "error":         None,
        "via_dlisio":    False,
    }

    # Primary: dlisio
    try:
        fields = _via_dlisio(file_path)
        result.update(fields)
        result["via_dlisio"] = True
        # Confidence: higher if we got at least well_name or uwi
        result["confidence"] = (
            0.85 if (result.get("well_name") or result.get("uwi"))
            else 0.40
        )
        return result
    except Exception as primary_err:
        result["error"] = f"dlisio: {primary_err}"

    # Fallback: raw scan
    try:
        fields = _via_raw_scan(file_path)
        result.update(fields)
        result["confidence"] = (
            0.50 if (result.get("well_name") or result.get("uwi"))
            else 0.15
        )
        # Append raw-scan note to error so caller knows fallback was used
        result["error"] = (result.get("error") or "") + " | raw scan used"
    except Exception as fallback_err:
        result["error"] = (result.get("error") or "") + f" | scan: {fallback_err}"

    return result
