"""
load_rrc_maf016.py
==================
Loads the RRC Texas MAF016 Master API File into dataview.dv_well.

The MAF016 file contains well header data for all Texas wells.
Download district files from:
  https://mft.rrc.texas.gov/link/701db9a3-32b5-488d-812b-cd6ff7d0fe85

District 3 (Permian Basin) = maf016.cc003  (recommended)
District files are named maf016.ccNNN where NNN is district number.

MAF016 Fixed-width layout (240 chars per record):
  [0:2]    Record type (32=active, 31=plugged, 30=cancelled)
  [2:3]    Filler
  [3:5]    RRC district code
  [5:8]    RRC county code
  [8:14]   Unique API sequence (6 digits)
  [14:15]  Sidetrack number
  [16:89]  Lease name / well name
  [89:121] Operator name (32 chars)
  [121:127] Total depth
  [182:214] Field name (32 chars)
  [214:222] Spud date YYYYMMDD
  [222:230] Completion date YYYYMMDD
  [238:240] Well type/status code (YO=oil, YG=gas, YW=water, etc.)

NOTE: This file has NO coordinates. Run load_rrc_w1_permits.py first
to get lat/lon from the W-1 drilling permit file, then use this file
to enrich with field name, TD, spud/completion dates.

Usage:
    python load_rrc_maf016.py --file "training/Texas/maf016.cc003"
    python load_rrc_maf016.py --file "maf016.cc003" --county "130,310,240"
    python load_rrc_maf016.py --file "maf016.cc003" --dry-run --limit 20
"""
from __future__ import annotations

import argparse
import sys
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

# ── RRC county code → county name (District 3 Permian Basin) ─────────
RRC_COUNTY = {
    "110": "CRANE",       "120": "CROCKETT",   "130": "ECTOR",
    "140": "GLASSCOCK",   "210": "HOWARD",      "220": "ANDREWS",
    "224": "ANDREWS",     "230": "LOVING",      "240": "MARTIN",
    "310": "MIDLAND",     "320": "PECOS",       "330": "REAGAN",
    "340": "UPTON",       "350": "TERRY",       "410": "WARD",
    "420": "WINKLER",     "430": "YOAKUM",      "440": "GAINES",
    "450": "DAWSON",      "460": "BORDEN",
    # District 8 (also in cc003)
    "510": "REEVES",      "520": "CULBERSON",   "530": "JEFF DAVIS",
}

# ── RRC county → FIPS (for UWI construction) ─────────────────────────
RRC_TO_FIPS = {
    "110": "103",  # CRANE
    "120": "105",  # CROCKETT
    "130": "135",  # ECTOR
    "140": "173",  # GLASSCOCK
    "210": "227",  # HOWARD
    "220": "003",  # ANDREWS
    "224": "003",  # ANDREWS
    "230": "301",  # LOVING
    "240": "317",  # MARTIN
    "310": "329",  # MIDLAND
    "320": "371",  # PECOS
    "330": "383",  # REAGAN
    "340": "461",  # UPTON
    "350": "445",  # TERRY
    "410": "475",  # WARD
    "420": "495",  # WINKLER
    "430": "501",  # YOAKUM
    "440": "165",  # GAINES
    "450": "115",  # DAWSON
    "460": "033",  # BORDEN
    "510": "389",  # REEVES
    "520": "109",  # CULBERSON
}

# ── Well type/status from YO/YG/YW codes ─────────────────────────────
WELL_TYPE = {
    "YO": "OIL",     "YG": "GAS",      "YW": "WATER",
    "YI": "INJECTION","YD": "DRY_HOLE", "  ": "OIL",
}

WELL_STATUS = {
    "32": "ACTIVE",  "31": "PLUGGED",  "30": "CANCELLED",
}


def _parse_date(s: str) -> str | None:
    s = (s or "").strip().replace(" ", "")
    if len(s) == 8 and s.isdigit() and s != "00000000":
        try:
            return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _clean(s: str) -> str:
    return " ".join(s.split()) if s else ""


def parse_maf016(
    filepath: str,
    county_filter: set | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Parse MAF016 fixed-width file, return list of well dicts."""
    wells  = []
    path   = Path(filepath)
    size   = path.stat().st_size / 1024 / 1024

    print(f"Parsing {path.name} ({size:.1f} MB)...")

    with open(filepath, encoding="latin-1", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            if len(line) < 200:
                continue

            rec_type = line[0:2].strip()
            if rec_type not in ("32", "31", "30"):
                continue

            county_c = line[5:8].strip()
            if not county_c.isdigit():
                continue

            # Apply county filter
            if county_filter:
                county_nm = RRC_COUNTY.get(county_c, "")
                fips      = RRC_TO_FIPS.get(county_c, "")
                if (county_c    not in county_filter and
                    county_nm   not in county_filter and
                    fips        not in county_filter):
                    continue

            unique   = line[8:14].strip()
            side     = line[14:15].strip() or "0"
            fips     = RRC_TO_FIPS.get(county_c, county_c.zfill(3))
            uwi      = f"US42{fips}{unique}{side.zfill(2)}0000"
            lease_nm = _clean(line[16:89])
            operator = _clean(line[89:121])
            td_s     = line[121:127].strip()
            field_nm = _clean(line[182:214])
            spud_s   = line[214:222].strip()
            compl_s  = line[222:230].strip()
            type_s   = line[238:240].strip() if len(line) >= 240 else ""

            td  = int(td_s) if td_s.isdigit() and int(td_s) > 0 else None
            wt  = WELL_TYPE.get(type_s, "OIL")
            ws  = WELL_STATUS.get(rec_type, "ACTIVE")

            wells.append({
                "uwi":           uwi,
                "well_name":     lease_nm[:80] or "UNKNOWN",
                "well_type":     wt,
                "well_status":   ws,
                "province_state":"TX",
                "country":       "US",
                "county":        RRC_COUNTY.get(county_c, county_c)[:50],
                "operator_name": operator[:80],
                "field_name":    field_nm[:80],
                "final_td":      td,
                "depth_datum":   "KB",
                "spud_date":     _parse_date(spud_s),
                "completion_date":_parse_date(compl_s),
                "api_num":       f"42-{fips}-{unique}-{side.zfill(2)}",
                "rrc_county":    county_c,
                "rrc_unique":    unique,
            })

            if limit and len(wells) >= limit:
                break

    print(f"Parsed {len(wells):,} well records")
    return wells


def load_wells(wells: list[dict], dry_run: bool = False) -> int:
    """
    Insert wells into dataview.dv_well.
    - If UWI exists: UPDATE field_name, operator, TD, dates (not coordinates)
    - If new: INSERT with NULL coordinates (enrich later with W-1 data)
    """
    if not wells:
        print("No wells to load")
        return 0

    # Get existing UWIs
    with eng.connect() as con:
        existing_uwis = set(pd.read_sql(
            text("SELECT uwi FROM dataview.dv_well"), con
        )["uwi"].tolist())

    new_wells    = [w for w in wells if w["uwi"] not in existing_uwis]
    update_wells = [w for w in wells if w["uwi"] in existing_uwis]

    print(f"New:    {len(new_wells):,}")
    print(f"Update: {len(update_wells):,}")

    if dry_run:
        print("\nDRY RUN — first 10 new wells:")
        for w in new_wells[:10]:
            print(f"  {w['uwi']} | {w['well_name'][:30]:30} | "
                  f"{w['operator_name'][:25]:25} | {w['county']:10} | "
                  f"TD={w['final_td']} | {w['field_name'][:25]}")
        print(f"\nFirst 5 updates:")
        for w in update_wells[:5]:
            print(f"  {w['uwi']} | {w['well_name'][:30]:30} | {w['field_name'][:25]}")
        return len(new_wells) + len(update_wells)

    inserted = updated = 0

    # Insert new wells (no coordinates — they come from W-1)
    if new_wells:
        rows = []
        for w in new_wells:
            rows.append({
                "uwi":             w["uwi"],
                "well_name":       w["well_name"],
                "well_type":       w["well_type"],
                "well_status":     w["well_status"],
                "province_state":  w["province_state"],
                "country":         w["country"],
                "county":          w["county"],
                "final_td":        w["final_td"],
                "depth_datum":     w["depth_datum"],
                "spud_date":       w["spud_date"],
                "completion_date": w["completion_date"],
                "api_num":         w["api_num"],
                "active_ind":      "Y" if w["well_status"] == "ACTIVE" else "N",
                "source":          "RRC_MAF016",
                "row_created_by":  "MAF016_LOADER",
                "row_changed_by":  "MAF016_LOADER",
            })

        df = pd.DataFrame(rows)
        chunk = 500
        with eng.begin() as con:
            for i in range(0, len(df), chunk):
                df.iloc[i:i+chunk].to_sql(
                    "dv_well", con, schema="dataview",
                    if_exists="append", index=False)
                inserted += len(df.iloc[i:i+chunk])
                print(f"  Inserted {inserted}/{len(df)}...")

    # Update existing wells with field/operator/TD info
    if update_wells:
        with eng.begin() as con:
            for w in update_wells:
                con.execute(text("""
                    UPDATE dataview.dv_well SET
                        well_status      = :ws,
                        final_td         = COALESCE(:td, final_td),
                        spud_date        = COALESCE(:spud, spud_date),
                        completion_date  = COALESCE(:compl, completion_date),
                        api_num          = COALESCE(NULLIF(:api,''), api_num),
                        row_changed_by   = 'MAF016_LOADER',
                        row_changed_date = GETDATE()
                    WHERE uwi = :uwi
                """), {
                    "uwi":   w["uwi"],
                    "ws":    w["well_status"],
                    "td":    w["final_td"],
                    "spud":  w["spud_date"],
                    "compl": w["completion_date"],
                    "api":   w["api_num"],
                })
                updated += 1
        print(f"Updated {updated:,} existing wells")

    return inserted + updated


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Load RRC MAF016 Master API File into DataView")
    ap.add_argument("--file", required=True,
                    help="Path to MAF016 file (e.g. maf016.cc003)")
    ap.add_argument("--county", default=None,
                    help="Comma-separated RRC county codes or names "
                         "(e.g. '130,310,240' or 'ECTOR,MIDLAND,MARTIN')")
    ap.add_argument("--limit",   type=int, default=None,
                    help="Max records to parse (for testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse only, do not insert")
    args = ap.parse_args()

    county_filter = None
    if args.county:
        county_filter = {c.strip().upper() for c in args.county.split(",")}

    wells = parse_maf016(args.file, county_filter, args.limit)

    if not wells:
        print("No wells found — check county filter")
        return

    # County summary
    cnts = {}
    for w in wells:
        cnts[w["county"]] = cnts.get(w["county"], 0) + 1
    print("\nCounty breakdown:")
    for c, n in sorted(cnts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c or 'UNKNOWN':20} {n:,}")

    print(f"\nTotal: {len(wells):,} wells")
    load_wells(wells, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
