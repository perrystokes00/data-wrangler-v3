"""
load_rrc_w1_permits.py
======================
Parses the RRC Texas W-1 Drilling Permit master file and loads
wells into dataview.dv_well.

The W-1 file is a multi-record-type fixed format where each permit
consists of several record types:
  01  - Well header: API, well name, county code, operator, permit date
  02  - Lease/field info, total depth, lease ID
  14: - Surface location (lat/lon decimal degrees)
  15: - Bottom hole location (lat/lon decimal degrees)

Usage:
    python load_rrc_w1_permits.py --file "path/to/w1_permits.txt"
    python load_rrc_w1_permits.py --file "w1.txt" --county "135,329,003"
    python load_rrc_w1_permits.py --file "w1.txt" --limit 1000 --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
    import urllib.parse
    from sqlalchemy import create_engine, text
except ImportError:
    sys.exit("pip install sqlalchemy pyodbc pandas")

# ── Connection ────────────────────────────────────────────────────────
SERVER   = r"127.0.0.1\SQLEXPRESS"
DATABASE = "DataView"

cs  = (f"DRIVER={{ODBC Driver 17 for SQL Server}};"
       f"SERVER={SERVER};DATABASE={DATABASE};Trusted_Connection=yes;")
eng = create_engine(
    "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(cs),
    fast_executemany=True,
)

# ── RRC County FIPS → name ────────────────────────────────────────────
COUNTY_MAP = {
    "003": "ANDREWS",    "033": "BORDEN",     "103": "CRANE",
    "109": "CULBERSON",  "115": "DAWSON",     "135": "ECTOR",
    "165": "GAINES",     "173": "GLASSCOCK",  "301": "LOVING",
    "317": "MARTIN",     "327": "MIDLAND",    "329": "MIDLAND",
    "371": "PECOS",      "383": "REAGAN",     "389": "REEVES",
    "445": "TERRY",      "461": "UPTON",      "475": "WARD",
    "495": "WINKLER",    "501": "YOAKUM",
    # Broader TX
    "011": "BLANCO",     "021": "BASTROP",    "051": "GRADY",
    "055": "GUADALUPE",  "085": "HIDALGO",    "099": "LUBBOCK",
    "113": "DALLAS",     "121": "DENTON",     "139": "ELLIS",
    "141": "EL PASO",    "157": "FORT BEND",  "161": "FRIO",
    "177": "GONZALES",   "191": "HARRIS",     "201": "HOUSTON",
    "203": "HOWARD",     "213": "JEFF DAVIS", "227": "MIDLAND",
    "237": "JACK",       "247": "JIM WELLS",  "255": "KARNES",
    "297": "LIVE OAK",   "309": "MCMULLEN",   "321": "MILLS",
    "361": "ORANGE",     "381": "REEVES",     "401": "RUSK",
    "405": "SAN AUGUSTINE","443": "TERRELL",  "461": "UPTON",
    "487": "WILBARGER",  "491": "WILLIAMSON",
}

# ── Well status from permit type ──────────────────────────────────────
PERMIT_STATUS = {
    "A": "ACTIVE", "E": "EXPIRED", "X": "CANCELLED",
    "P": "PLUGGED", "N": "APPROVED", " ": "APPROVED",
}

WELL_TYPE_MAP = {
    "O": "OIL", "G": "GAS", "W": "WATER SUPPLY", "I": "INJECTION",
    "D": "DRY HOLE", "H": "HORIZONTAL", " ": "OIL",
}


def _parse_date(s: str) -> str | None:
    s = (s or "").strip()
    if len(s) == 8 and s.isdigit():
        try:
            return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _make_uwi(county_c: str, api9: str) -> str:
    """Build UWI from RRC county code (3 digits) and API sequence (9 digits).
    Format: US42 + county(3) + api9(9) = 16 chars, matching DataView standard.
    """
    return f"US42{county_c.zfill(3)}{api9.strip().zfill(9)}"


def parse_w1_file(
    filepath: str,
    county_filter: set | None = None,
    limit: int | None = None,
) -> list[dict]:
    """
    Parse W-1 permit file, return list of well dicts.
    Groups records by permit block (starts with '01' record).
    """
    wells  = []
    current: dict = {}

    path = Path(filepath)
    print(f"Parsing {path.name} ({path.stat().st_size/1024/1024:.1f} MB)...")

    with open(filepath, encoding="latin-1", errors="replace") as f:
        for line in f:
            if len(line) < 2:
                continue

            rec = line[:2]

            # ── Record 01: Well header ────────────────────────────
            if rec == "01":
                # Save previous well if complete
                if current.get("api") and current.get("lat"):
                    wells.append(current)
                    if limit and len(wells) >= limit:
                        break

                current = {}
                try:
                    # Format: 01 + API(10) + well_num(4) + permit#(8) + date(8) + operator(32) + ...
                    # Record 01 layout (0-indexed):
                    #  0- 2: record type "01"
                    #  2-11: api9 (9-digit RRC sequence)
                    # 11-14: county code (3 digits)
                    # 14-46: well name (32 chars)
                    # 46-54: permit number (8 digits)
                    # 54-58: spaces
                    # 58-66: permit date YYYYMMDD
                    # 66-98: operator name (32 chars)
                    api9      = line[2:11].strip()
                    county_c  = line[11:14].strip()
                    well_name = line[14:46].strip()
                    permit_no = line[46:54].strip()
                    pdate     = line[58:66].strip() if len(line) > 66 else ""
                    operator  = line[66:98].strip() if len(line) > 98 else ""

                    current = {
                        "api":        f"42-{county_c}-{api9}",
                        "uwi":        _make_uwi(county_c, api9),
                        "well_name":  well_name,
                        "permit_no":  permit_no,
                        "permit_date":_parse_date(pdate),
                        "operator":   operator,
                        "county_code":county_c.zfill(3),
                        "county":     COUNTY_MAP.get(county_c.zfill(3), county_c),
                        "well_type":  "OIL",
                        "well_status":"APPROVED",
                        "lat":        None,
                        "lon":        None,
                        "bh_lat":     None,
                        "bh_lon":     None,
                        "field":      "",
                        "td":         None,
                        "spud_date":  None,
                        "compl_date": None,
                    }
                except Exception:
                    current = {}

            # ── Record 02: Lease/TD info ──────────────────────────
            elif rec == "02" and current:
                try:
                    td_s = line[86:94].strip() if len(line) > 94 else ""
                    if td_s.isdigit() and int(td_s) > 0:
                        current["td"] = int(td_s)
                    spud = line[106:114].strip() if len(line) > 114 else ""
                    current["spud_date"] = _parse_date(spud)
                    compl = line[114:122].strip() if len(line) > 122 else ""
                    current["compl_date"] = _parse_date(compl)
                except Exception:
                    pass

            # ── Record 14: Surface lat/lon ────────────────────────
            elif line.startswith("14:") and current:
                try:
                    parts = line[3:].strip().split()
                    if len(parts) >= 2:
                        lon = float(parts[0])
                        lat = float(parts[1])
                        if -180 <= lon <= 180 and -90 <= lat <= 90:
                            current["lat"] = lat
                            current["lon"] = lon
                except (ValueError, IndexError):
                    pass

            # ── Record 15: Bottom hole lat/lon ────────────────────
            elif line.startswith("15:") and current:
                try:
                    parts = line[3:].strip().split()
                    if len(parts) >= 2:
                        current["bh_lon"] = float(parts[0])
                        current["bh_lat"] = float(parts[1])
                except (ValueError, IndexError):
                    pass

        # Don't forget last well
        if current.get("api") and current.get("lat"):
            wells.append(current)

    # Apply county filter
    if county_filter:
        wells = [w for w in wells if w["county_code"] in county_filter
                 or w["county"].upper() in {c.upper() for c in county_filter}]

    print(f"Parsed {len(wells)} wells with coordinates")
    return wells


def load_wells(wells: list[dict], dry_run: bool = False) -> int:
    """Insert parsed wells into dataview.dv_well. Skips existing UWIs."""

    if not wells:
        print("No wells to load")
        return 0

    # Get existing UWIs
    with eng.connect() as con:
        existing = set(pd.read_sql(
            text("SELECT uwi FROM dataview.dv_well"), con
        )["uwi"].tolist())

    new_wells = [w for w in wells if w["uwi"] not in existing]
    print(f"New wells to insert: {len(new_wells)} "
          f"({len(wells)-len(new_wells)} already exist)")

    if dry_run:
        print("DRY RUN — no data inserted")
        for w in new_wells[:5]:
            print(f"  {w['uwi']} | {w['well_name']} | "
                  f"{w['county']} | {w['operator']} | "
                  f"{w['lat']:.4f}, {w['lon']:.4f}")
        return len(new_wells)

    if not new_wells:
        return 0

    rows = []
    for w in new_wells:
        rows.append({
            "uwi":               w["uwi"],
            "well_name":         w["well_name"][:80] if w["well_name"] else "UNKNOWN",
            "well_type":         w.get("well_type","OIL"),
            "well_status":       "ACTIVE",
            "province_state":    "TX",
            "country":           "US",
            "county":            w.get("county","")[:50],
            "surface_latitude":  w["lat"],
            "surface_longitude": w["lon"],
            "bh_latitude":       w.get("bh_lat"),
            "bh_longitude":      w.get("bh_lon"),
            "final_td":          w.get("td"),
            "depth_datum":       "KB",
            "spud_date":         w.get("spud_date"),
            "completion_date":   w.get("compl_date"),
            "api_num":           w.get("api","")[:20],
            "active_ind":        "Y",
            "source":            "RRC_TX_W1",
            "row_created_by":    "RRC_LOADER",
            "row_changed_by":    "RRC_LOADER",
        })

    df = pd.DataFrame(rows)

    # Chunk insert
    chunk = 500
    inserted = 0
    with eng.begin() as con:
        for i in range(0, len(df), chunk):
            batch = df.iloc[i:i+chunk]
            batch.to_sql("dv_well", con, schema="dataview",
                         if_exists="append", index=False)
            inserted += len(batch)
            print(f"  Inserted {inserted}/{len(df)}...")

    print(f"Done — {inserted} wells loaded")
    return inserted


def main() -> None:
    ap = argparse.ArgumentParser(description="Load RRC W-1 permits into DataView")
    ap.add_argument("--file",   required=True, help="Path to W-1 permit text file")
    ap.add_argument("--county", default=None,
                    help="Comma-separated county codes or names to filter "
                         "(e.g. '135,329,003' or 'MIDLAND,ECTOR,ANDREWS')")
    ap.add_argument("--limit",   type=int, default=None,
                    help="Max wells to parse (for testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse only, show first 5 results, do not insert")
    args = ap.parse_args()

    county_filter = None
    if args.county:
        county_filter = {c.strip().upper() for c in args.county.split(",")}

    wells = parse_w1_file(args.file, county_filter, args.limit)

    if not wells:
        print("No wells matched — check county filter or file format")
        return

    # Summary
    counties = {}
    for w in wells:
        counties[w["county"]] = counties.get(w["county"], 0) + 1
    print("\nCounty breakdown:")
    for c, n in sorted(counties.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c or 'UNKNOWN':20} {n:,}")

    load_wells(wells, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
