"""
deploy_federation.py
====================
Copies federation-capable files from data_wrangler_v3 to wrangler_view.
Creates the directory structure and copies all loaders, exporters,
map, and federation tools.

Usage:
    python deploy_federation.py
    python deploy_federation.py --dry-run
"""
import argparse, shutil, os
from pathlib import Path

V3_ROOT = Path(
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai"
    r"\data_wrangler\data_wrangler_v3"
)
WV_ROOT = Path(
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai"
    r"\wrangler_view"
)

# Files to copy: (source in v3, destination in wrangler_view)
COPY_FILES = [
    # ── Federation Map ────────────────────────────────────────
    ("federation_map.py",               "federation_map.py"),
    ("start_federation_map.bat",        "start_federation_map.bat"),

    # ── Loaders ───────────────────────────────────────────────
    ("load_kgs_geojson.py",             "loaders/load_kgs_geojson.py"),
    ("load_nd_gdb.py",                  "loaders/load_nd_gdb.py"),
    ("load_ok_csv.py",                  "loaders/load_ok_csv.py"),
    ("enrich_from_dbf.py",              "loaders/enrich_from_dbf.py"),

    # ── Snowflake Pipeline ────────────────────────────────────
    ("export_for_snowflake.bat",        "snowflake/export_for_snowflake.bat"),
    ("upload_to_snowflake.py",          "snowflake/upload_to_snowflake.py"),
    ("well_matching.sql",               "snowflake/well_matching.sql"),

    # ── GeoJSON Builders ──────────────────────────────────────
    ("build_county_geojson.py",         "tools/build_county_geojson.py"),
    ("build_geojson_from_snowflake.py", "tools/build_geojson_from_snowflake.py"),

    # ── Import Page ───────────────────────────────────────────
    ("page_dv_importer.py",             "pages/page_dv_importer.py"),

    # ── Well Map ──────────────────────────────────────────────
    ("page_well_map.py",                "pages/page_well_map.py"),

    # ── Existing loaders from v3 ──────────────────────────────
    ("page_import_shapefile.py",        "loaders/page_import_shapefile.py"),
    ("page_import_gom.py",              "loaders/page_import_gom.py"),
    ("page_import_gom_dir_srvy.py",     "loaders/page_import_gom_dir_srvy.py"),
    ("page_import_osdu.py",             "loaders/page_import_osdu.py"),
    ("page_import_witsml.py",           "loaders/page_import_witsml.py"),
    ("page_import_rrc.py",              "loaders/page_import_rrc.py"),
    ("prep_rrc_texas.py",               "parsers/prep_rrc_texas.py"),

    # ── Federation Spec ───────────────────────────────────────
    ("federation_spec.md",              "docs/federation_spec.md"),
]

# Directories to create
CREATE_DIRS = [
    "loaders",
    "snowflake",
    "tools",
    "pages",
    "parsers",
    "docs",
    "geojson",
    "well_icons",
]

# New files to create in wrangler_view
NEW_FILES = {
    "README.md": """# WranglerView v1

**Well Data Federation Platform**

Federates publicly available well data from US state agencies and federal
sources into a unified Snowflake database. 2M+ wells across TX, KS, OK, ND, and GOM.

## Quick Start

```bash
# Start the federation map
start_federation_map.bat

# Or manually:
set SNOWFLAKE_PASSWORD=your_password
streamlit run federation_map.py --server.port 8503
```

## Data Pipeline

```
State Agency → BCP Export → PUT/COPY INTO → Snowflake RAW → WELL_MASTER → Map
```

### Load new data:
```bash
python loaders/load_kgs_geojson.py        # Kansas
python loaders/load_nd_gdb.py             # North Dakota
python loaders/load_ok_csv.py             # Oklahoma
python loaders/enrich_from_dbf.py         # Texas DBF enrichment
```

### Push to Snowflake:
```bash
snowflake\\export_for_snowflake.bat       # BCP export CSVs
python snowflake\\upload_to_snowflake.py   # PUT + COPY INTO
```

### Build GeoJSON for map:
```bash
python tools\\build_county_geojson.py --region all-regions
python tools\\build_geojson_from_snowflake.py --state all
```

## Coverage

| State | Wells | Source |
|-------|-------|--------|
| Texas | 989K | RRC shapefiles + DBF enrichment |
| Kansas | 477K | KGS GeoJSON |
| Oklahoma | 442K | OCC CSV |
| GOM | 55K | BOEM |
| North Dakota | 44K | NDIC GDB |
| **Total** | **2M+** | |

## Architecture

- **Local**: SQL Server Express (DataView database)
- **Cloud**: Snowflake (WELL_FEDERATION database)
- **Map**: Streamlit + pydeck (federation_map.py)
- **Pipeline**: BCP → PUT → COPY INTO (44 seconds for 1.5M wells)

## License

Proprietary — Data Wrangler Solutions LLC
""",

    ".gitignore": """__pycache__/
*.pyc
.env
venv/
.venv/
geojson/
*.csv
*.shp
*.dbf
*.shx
*.prj
*.zip
*.geojson
C:\\Bulk\\
""",

    "requirements.txt": """streamlit>=1.45.0
pandas>=2.2.3
sqlalchemy>=2.0
pyodbc
snowflake-connector-python
snowflake-sqlalchemy
fiona
pydeck
folium
streamlit-folium
dbfread
""",
}


def deploy(dry_run=False):
    print("WranglerView — Deploy Federation")
    print(f"  Source: {V3_ROOT}")
    print(f"  Target: {WV_ROOT}")
    print(f"  Dry run: {dry_run}")
    print()

    # Create directories
    for d in CREATE_DIRS:
        path = WV_ROOT / d
        if not path.exists():
            if not dry_run:
                path.mkdir(parents=True, exist_ok=True)
            print(f"  📁 {d}/")

    # Copy files
    copied = 0
    skipped = 0
    missing = 0
    for src_rel, dst_rel in COPY_FILES:
        src = V3_ROOT / src_rel
        dst = WV_ROOT / dst_rel
        if not src.exists():
            print(f"  ✗ {src_rel} (not found)")
            missing += 1
            continue
        if dst.exists():
            # Compare modification times
            if src.stat().st_mtime <= dst.stat().st_mtime:
                skipped += 1
                continue
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        copied += 1
        size_kb = src.stat().st_size / 1024
        print(f"  ✓ {src_rel} → {dst_rel} ({size_kb:.0f} KB)")

    # Copy well_icons directory
    icons_src = V3_ROOT / "well_icons"
    icons_dst = WV_ROOT / "well_icons"
    if icons_src.exists() and icons_src.is_dir():
        if not dry_run:
            if icons_dst.exists():
                shutil.rmtree(str(icons_dst))
            shutil.copytree(str(icons_src), str(icons_dst))
        n = sum(1 for _ in icons_src.rglob("*") if _.is_file())
        print(f"  ✓ well_icons/ ({n} files)")
        copied += n

    # Create new files
    for rel_path, content in NEW_FILES.items():
        dst = WV_ROOT / rel_path
        if not dst.exists():
            if not dry_run:
                dst.write_text(content, encoding="utf-8")
            print(f"  + {rel_path}")

    print(f"\n  Copied: {copied}, Skipped: {skipped}, Missing: {missing}")

    if not dry_run:
        print(f"\n  Done! Next steps:")
        print(f"    cd {WV_ROOT}")
        print(f"    git add -A")
        print(f"    git commit -m \"Federation deploy from v3\"")
        print(f"    git push origin master")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    deploy(args.dry_run)


if __name__ == "__main__":
    main()
