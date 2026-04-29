from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SEEDS_DIR = ROOT / "seeds"
CATALOG_DIR = ROOT / "catalog"
OUT_FILE = CATALOG_DIR / "ppdm39_seed_catalog.json"

MODEL_DEFAULT = "ppdm39"
VERSION_DEFAULT = "1.0"
MODE_DEFAULT = "missing_only"


# ------------------------------------------------------------------
# Load helpers
# ------------------------------------------------------------------
def load_json(path: Path) -> Dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to read {path}: {e}")


def is_seed_payload(data: Dict) -> bool:
    """
    Seed payload rules:
      - must have "name"
      - must have "rows" as a list
    """
    return (
        isinstance(data, dict)
        and isinstance(data.get("name"), str)
        and isinstance(data.get("rows"), list)
    )


# ------------------------------------------------------------------
# Priority ordering (safe PPDM defaults)
# ------------------------------------------------------------------
PRIORITY_PREFIX = [
    "dbo.r_",
    "dbo.cs_",
    "dbo.ppdm_",
    "dbo.area",
    "dbo.contain",
]


def seed_priority(table: str) -> int:
    """
    Lower number loads earlier.
    """
    for i, p in enumerate(PRIORITY_PREFIX):
        if table.startswith(p):
            return i
    return len(PRIORITY_PREFIX) + 10


# ------------------------------------------------------------------
# Main catalog build
# ------------------------------------------------------------------
def build_catalog() -> Dict:
    entries: List[Dict] = []

    if not SEEDS_DIR.exists():
        raise RuntimeError(f"Seeds directory not found: {SEEDS_DIR}")

    for path in sorted(SEEDS_DIR.glob("*.json")):
        data = load_json(path)

        # Skip existing catalogs or non-seed JSON
        if "entries" in data:
            continue

        if not is_seed_payload(data):
            continue

        table = data["name"]

        entry = {
            "table": table,
            "file": f"seeds/{path.name}",
            "format": "json",
            "mode": MODE_DEFAULT,
            "model": data.get("model", MODEL_DEFAULT),
            "version": data.get("version", VERSION_DEFAULT),
        }

        entries.append(entry)

    # Sort entries by PPDM-safe priority then name
    entries.sort(key=lambda e: (seed_priority(e["table"]), e["table"]))

    catalog = {
        "name": "ppdm39_seed_catalog",
        "model": MODEL_DEFAULT,
        "version": VERSION_DEFAULT,
        "root": str(ROOT),
        "entries": entries,
    }

    return catalog


# ------------------------------------------------------------------
# Write output
# ------------------------------------------------------------------
def main():
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)

    catalog = build_catalog()
    OUT_FILE.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    print(f"✔ Seed catalog written: {OUT_FILE}")
    print(f"✔ Entries: {len(catalog['entries'])}")


if __name__ == "__main__":
    main()
