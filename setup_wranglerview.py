"""
setup_wranglerview.py
=====================
Sets up the WranglerView v1 repository by copying required components
from DataView v3 and initializing the project structure.

Usage:
    python setup_wranglerview.py
    python setup_wranglerview.py --v3-root "C:\path\to\data_wrangler_v3"
    python setup_wranglerview.py --target "C:\path\to\wrangler_view"

Run from anywhere. Copies files, creates directories, initializes git.
"""
from __future__ import annotations

import argparse
import shutil
import os
from pathlib import Path


# ── Default paths ─────────────────────────────────────────────────────

DEFAULT_V3 = Path(
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai"
    r"\data_wrangler\data_wrangler_v3"
)
DEFAULT_TARGET = Path(
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai"
    r"\wrangler_view"
)


# ── Files to copy from v3 ────────────────────────────────────────────

# (source_relative_path, target_relative_path)
# None for target means same relative path
COPY_FILES = [
    # ── Core app ──────────────────────────────────────────────
    # NOT copying app_v3.py — WranglerView gets its own app.py

    # ── Map ───────────────────────────────────────────────────
    ("page_well_map.py",              "pages/page_well_map.py"),
    ("build_well_geojson.py",         "tools/build_well_geojson.py"),

    # ── Parsers / Loaders ─────────────────────────────────────
    ("prep_rrc_texas.py",             "parsers/prep_rrc_texas.py"),
    ("page_import_rrc.py",            "loaders/page_import_rrc.py"),
    ("page_import_shapefile.py",      "loaders/page_import_shapefile.py"),
    ("page_import_osdu.py",           "loaders/page_import_osdu.py"),
    ("page_import_witsml.py",         "loaders/page_import_witsml.py"),
    ("page_import_gom.py",            "loaders/page_import_gom.py"),
    ("page_import_gom_dir_srvy.py",   "loaders/page_import_gom_dir_srvy.py"),

    # ── Catalog / Extractors ──────────────────────────────────
    ("json_well_log_catalog.py",      "extractors/json_well_log_catalog.py"),
    ("witsml_catalog.py",             "extractors/witsml_catalog.py"),
    ("file_summarizer.py",            "extractors/file_summarizer.py"),

    # ── Well icons ────────────────────────────────────────────
    # Copied as a directory below

    # ── Modules (shared utilities) ────────────────────────────
    ("modules/db_pool.py",            "modules/db_pool.py"),
]

# Directories to copy wholesale
COPY_DIRS = [
    ("well_icons",                    "assets/well_icons"),
]

# ── New files to create ──────────────────────────────────────────────

NEW_FILES = {
    # ── README ────────────────────────────────────────────────
    "README.md": """# WranglerView v1

**Well Data Federation Platform**

Federates publicly available well data from US state agencies and federal
sources into a single, cohesive database. Supports SQL Server (prototype)
and Snowflake (production).

## Architecture

```
Raw Ingest → Normalize → Match → Curate → Enrich → Visualize
```

- **Raw schemas** — per-state, mirrors source format exactly
- **Curated layer** — one row per physical wellbore (WELL_MASTER)
- **Enriched layer** — production rollups, decline curves, spacing
- **Map** — pydeck/Folium WebGL rendering from pre-built GeoJSON

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

## Components

| Directory | Purpose |
|-----------|---------|
| `parsers/` | Source file parsers (RRC, OSDU, WITSML) |
| `loaders/` | Database loaders (Streamlit UI) |
| `extractors/` | File catalog extractors |
| `federation/` | Matching algorithm, ETL pipeline |
| `pages/` | Streamlit page modules |
| `tools/` | CLI utilities (GeoJSON builder, etc.) |
| `sql/` | DDL scripts (SQL Server + Snowflake) |
| `modules/` | Shared Python modules |
| `assets/` | Well icons, static files |

## Data Sources

- Texas RRC (MAF016, shapefiles, production)
- Kansas KGS (well headers)
- BOEM (Gulf of America wells + directional surveys)
- OSDU JSON (16 schema kinds)
- WITSML (trajectory, log, mudLog, well)
- Any well shapefile

## License

Proprietary — Data Wrangler Solutions LLC
""",

    # ── Requirements ──────────────────────────────────────────
    "requirements.txt": """streamlit==1.45.0
pandas==2.2.3
sqlalchemy>=2.0
pyodbc
snowflake-sqlalchemy
snowflake-connector-python
geopandas
folium
streamlit-folium
pydeck
click==8.1.7
""",

    # ── Config ────────────────────────────────────────────────
    "config.py": '''"""
WranglerView configuration.
Connection strings, paths, and defaults.
"""
import os

# ── Database connections ──────────────────────────────────────────

# SQL Server (prototype / local development)
SQLSERVER_CONN = (
    "mssql+pyodbc://127.0.0.1\\\\SQLEXPRESS/WranglerView"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
    "&TrustServerCertificate=yes"
)

# Snowflake (production federation)
SNOWFLAKE_CONN = (
    "snowflake://{user}:{password}@{account}/WELL_FEDERATION/CURATED"
    "?warehouse=WV_WH&role=WV_ROLE"
).format(
    user=os.environ.get("SNOWFLAKE_USER", ""),
    password=os.environ.get("SNOWFLAKE_PASSWORD", ""),
    account=os.environ.get("SNOWFLAKE_ACCOUNT", ""),
)

# Active connection — switch between SQL Server and Snowflake
DB_DIALECT = os.environ.get("WV_DIALECT", "sqlserver")  # "sqlserver" or "snowflake"

# ── Paths ─────────────────────────────────────────────────────────
GEOJSON_PATH = "wells.geojson"

# ── Mapbox ────────────────────────────────────────────────────────
MAPBOX_TOKEN = os.environ.get("MAPBOX_API_KEY", "")
''',

    # ── .gitignore ────────────────────────────────────────────
    ".gitignore": """__pycache__/
*.pyc
.env
*.bak
venv/
.venv/
wells.geojson
*.csv
*.shp
*.dbf
*.shx
*.prj
*.sbn
*.sbx
*.zip
dist/
build/
""",

    # ── .env template ─────────────────────────────────────────
    ".env.template": """# WranglerView environment variables
# Copy to .env and fill in values

# Snowflake connection
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_ACCOUNT=

# Database dialect: "sqlserver" or "snowflake"
WV_DIALECT=sqlserver

# Mapbox API key (for satellite basemaps)
MAPBOX_API_KEY=pk.your_key_here
""",
}


# ── Directories to create ────────────────────────────────────────

CREATE_DIRS = [
    "parsers",
    "loaders",
    "extractors",
    "federation",
    "pages",
    "tools",
    "sql",
    "sql/sqlserver",
    "sql/snowflake",
    "modules",
    "assets",
    "assets/well_icons",
    "tests",
]


def setup(v3_root: Path, target: Path):
    """Set up the WranglerView repository."""
    print(f"WranglerView v1 Setup")
    print(f"  Source (DataView v3): {v3_root}")
    print(f"  Target:              {target}")
    print()

    if not v3_root.exists():
        print(f"ERROR: DataView v3 root not found: {v3_root}")
        return False

    # Create target directory
    target.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    for d in CREATE_DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)
        # Add __init__.py to Python packages
        if not d.startswith("sql") and not d.startswith("assets"):
            init = target / d / "__init__.py"
            if not init.exists():
                init.write_text("")
    print(f"  Created {len(CREATE_DIRS)} directories")

    # Copy files from v3
    copied = 0
    skipped = 0
    for src_rel, dst_rel in COPY_FILES:
        src = v3_root / src_rel
        dst = target / dst_rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            copied += 1
            print(f"  ✓ {src_rel} → {dst_rel}")
        else:
            skipped += 1
            print(f"  ✗ {src_rel} (not found, skipping)")

    # Copy directories
    for src_rel, dst_rel in COPY_DIRS:
        src = v3_root / src_rel
        dst = target / dst_rel
        if src.exists() and src.is_dir():
            if dst.exists():
                shutil.rmtree(str(dst))
            shutil.copytree(str(src), str(dst))
            n = sum(1 for _ in dst.rglob("*") if _.is_file())
            copied += n
            print(f"  ✓ {src_rel}/ → {dst_rel}/ ({n} files)")
        else:
            print(f"  ✗ {src_rel}/ (not found, skipping)")

    print(f"\n  Copied: {copied} files, Skipped: {skipped}")

    # Create new files
    created = 0
    for rel_path, content in NEW_FILES.items():
        dst = target / rel_path
        if not dst.exists():
            dst.write_text(content, encoding="utf-8")
            created += 1
            print(f"  + {rel_path}")
        else:
            print(f"  = {rel_path} (already exists)")
    print(f"  Created: {created} new files")

    # Initialize git
    git_dir = target / ".git"
    if not git_dir.exists():
        os.system(f'cd "{target}" && git init && git add -A && '
                  f'git commit -m "WranglerView v1 initial setup from DataView v3"')
        print(f"\n  Git initialized with initial commit")
    else:
        print(f"\n  Git already initialized")

    print(f"\nDone! Next steps:")
    print(f"  cd {target}")
    print(f"  python -m venv venv")
    print(f"  venv\\Scripts\\activate")
    print(f"  pip install -r requirements.txt")
    print(f"  git remote add origin https://github.com/perrystokes00/wrangler-view.git")
    print(f"  git push -u origin master")

    return True


def main():
    ap = argparse.ArgumentParser(
        description="Set up WranglerView v1 from DataView v3")
    ap.add_argument("--v3-root", type=Path, default=DEFAULT_V3,
                    help="Path to DataView v3 root")
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET,
                    help="Path for new WranglerView repo")
    args = ap.parse_args()
    setup(args.v3_root, args.target)


if __name__ == "__main__":
    main()
