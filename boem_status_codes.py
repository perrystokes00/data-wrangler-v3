"""
boem_status_codes.py
====================
BOEM/BSEE well status_code → friendly-name lookup.

Used by page_well_map.py to label the status filter checkboxes when the
active area is GOM (dataview_gom.well). Codes are the raw status_code
values found in that table.

Only codes whose meaning is confidently or reasonably-confidently known
are mapped. Anything not in the dict — currently AST and VCW — falls
through to its raw code via status_name(), rather than risk a wrong
label. If BOEM's official status-code definitions are pulled later,
fill in the remaining entries here.

Code frequencies at time of writing (dataview_gom.well):
    PA  30429   ST 17081   COM 3852   TA 3029   CNL 992
    DSI    48   APD   17   DRL   13   AST   13   VCW    2
"""

# status_code → friendly name. Confident + reasonably-confident only.
BOEM_STATUS_NAMES = {
    "PA":  "Permanently Abandoned",
    "TA":  "Temporarily Abandoned",
    "COM": "Completed",
    "DRL": "Drilling",
    "APD": "Approved Permit to Drill",
    "CNL": "Cancelled",
    "ST":  "Sidetrack",
    "DSI": "Drilled and Shut-In",
    # AST — not confidently known, intentionally omitted (passes through)
    # VCW — not confidently known, intentionally omitted (passes through)
}

# status_code → fixed hex color for map markers and checkbox swatches.
# Categorical, not a gradient — each code gets one stable color so the
# map reads the same every session. Covers all 10 codes seen in
# dataview_gom.well; _STATUS_FALLBACK_COLOR catches anything unexpected.
# Palette chosen for reasonable separation on both light and satellite
# basemaps.
BOEM_STATUS_COLORS = {
    "PA":  "#dc2626",  # red        — permanently abandoned
    "ST":  "#2563eb",  # blue       — sidetrack
    "COM": "#16a34a",  # green      — completed
    "TA":  "#f59e0b",  # amber      — temporarily abandoned
    "CNL": "#6b7280",  # gray       — cancelled
    "DSI": "#9333ea",  # purple     — drilled & shut-in
    "APD": "#0891b2",  # cyan       — approved permit to drill
    "DRL": "#ea580c",  # orange     — drilling
    "AST": "#db2777",  # pink       — (meaning unconfirmed)
    "VCW": "#65a30d",  # olive      — (meaning unconfirmed)
}
_STATUS_FALLBACK_COLOR = "#94a3b8"  # slate — any code not in the map


def status_color(code: str) -> str:
    """
    Return the fixed hex color for a BOEM status code, or a neutral
    slate fallback for any code not in BOEM_STATUS_COLORS. Never raises.
    """
    if not code:
        return _STATUS_FALLBACK_COLOR
    key = str(code).strip().upper()
    return BOEM_STATUS_COLORS.get(key, _STATUS_FALLBACK_COLOR)


def status_name(code: str) -> str:
    """
    Return the friendly name for a BOEM status code, or the raw code
    itself (uppercased, stripped) if it isn't in the lookup. Never
    raises — an unknown code just falls through to itself.
    """
    if not code:
        return ""
    key = str(code).strip().upper()
    return BOEM_STATUS_NAMES.get(key, key)


def status_label(code: str) -> str:
    """
    Checkbox-friendly label: "Permanently Abandoned (PA)" when a name is
    known, or just "PA" when it isn't. Keeps the raw code visible either
    way so it's still recognizable against the underlying data.
    """
    if not code:
        return ""
    key = str(code).strip().upper()
    name = BOEM_STATUS_NAMES.get(key)
    return f"{name} ({key})" if name else key
