"""
prep_rrc_texas.py
=================
Preprocesses RRC Texas MAF016 + W-1 permit files into a single CSV
ready for the DataView importer UI.

Usage:
    python prep_rrc_texas.py --maf016 "training/Texas/maf016.cc003"
    python prep_rrc_texas.py --maf016 "maf016.cc003" --w1 "w1permits.txt"
    python prep_rrc_texas.py --maf016 "maf016.cc003" --w1 "w1.txt" --county "135,329,003"
    python prep_rrc_texas.py --maf016 "maf016.cc003" --limit 5000

Output:
    rrc_texas_wells.csv  — ready to drag into DataView importer
    Columns map to dv_well via fingerprint or auto-mapping:
      API_NUM_NODASH  → uwi
      API_NUMBER      → api_num
      WELL_NAME       → well_name
      OPERATOR        → operator_ba_id / current_operator_ba_id
      FIELD           → field_id
      COUNTY          → county
      STATE           → province_state
      LATITUDE        → surface_latitude
      LONGITUDE       → surface_longitude
      FINAL_TD        → final_td
      DEPTH_DATUM     → depth_datum
      SPUD_DATE       → spud_date
      COMPLETION_DATE → completion_date
      WELL_TYPE       → well_type
      WELL_STATUS     → well_status
      SOURCE          → (literal RRC_TX)
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("pip install pandas")

# ── RRC county code → FIPS ────────────────────────────────────────────
RRC_TO_FIPS = {
    "110": "103", "120": "105", "130": "105", "224": "003",
    "220": "003", "230": "301", "240": "317", "310": "329",
    "320": "371", "330": "383", "340": "461", "350": "445",
    "410": "475", "420": "495", "430": "501", "440": "165",
    "450": "115", "460": "033", "510": "389", "520": "109",
    "130": "135", "140": "173", "210": "227",
}

RRC_COUNTY = {
    "110": "CRANE",    "120": "CROCKETT", "130": "ECTOR",
    "140": "GLASSCOCK","210": "HOWARD",   "220": "ANDREWS",
    "224": "ANDREWS",  "230": "LOVING",   "240": "MARTIN",
    "310": "MIDLAND",  "320": "PECOS",    "330": "REAGAN",
    "340": "UPTON",    "350": "TERRY",    "410": "WARD",
    "420": "WINKLER",  "430": "YOAKUM",   "440": "GAINES",
    "450": "DAWSON",   "460": "BORDEN",   "510": "REEVES",
    "520": "CULBERSON",
}

WELL_TYPE = {
    "YO": "OIL", "YG": "GAS", "YW": "WATER",
    "YI": "INJECTION", "YD": "DRY_HOLE", "  ": "OIL", "": "OIL",
}

WELL_STATUS = {
    "32": "ACTIVE", "31": "PLUGGED", "30": "CANCELLED",
}


def _parse_date(s: str) -> str:
    s = (s or "").strip().replace(" ", "")
    if len(s) == 8 and s.isdigit() and s != "00000000":
        try:
            return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _clean(s: str) -> str:
    return " ".join(s.split()) if s else ""


def _make_uwi_14(fips: str, seq: str, side: str = "0") -> str:
    """Build 14-digit no-dash UWI: 42 + fips(3) + seq(5) + side(2) + event(2)"""
    seq_clean = re.sub(r"[^0-9]", "", seq).zfill(5)[-5:]
    side_clean = re.sub(r"[^0-9]", "", side).zfill(2)[-2:]
    return f"42{fips.zfill(3)}{seq_clean}{side_clean}00"


def parse_maf016(filepath: str, county_filter: set | None,
                 limit: int | None) -> list[dict]:
    print(f"\nParsing MAF016: {filepath}")
    wells = []
    with open(filepath, encoding="latin-1", errors="replace") as f:
        for line in f:
            if len(line) < 200:
                continue
            rec_type = line[0:2].strip()
            if rec_type not in ("32", "31", "30"):
                continue
            county_c = line[5:8].strip()
            if not county_c.isdigit():
                continue
            if county_filter and county_c not in county_filter:
                continue

            fips   = RRC_TO_FIPS.get(county_c, county_c.zfill(3))
            seq    = line[8:14].strip()
            side   = line[14:15].strip() or "0"
            uwi_14 = _make_uwi_14(fips, seq, side)

            # API number dashed format
            api_num = f"42-{fips}-{seq.zfill(5)}-{side.zfill(2)}"

            lease_nm = _clean(line[16:71])
            operator = _clean(line[89:121])

            td_s  = "".join(c for c in line[121:127] if c.isdigit())
            td    = td_s if td_s and int(td_s) > 0 else ""

            field = _clean(line[182:214])
            spud  = _parse_date(line[214:222]) if len(line) >= 222 else ""
            compl = _parse_date(line[222:230]) if len(line) >= 230 else ""
            type_s = line[238:240].strip() if len(line) >= 240 else ""

            wells.append({
                "API_NUM_NODASH":  uwi_14,
                "API_NUMBER":      api_num,
                "LEASE":           lease_nm[:80] or "UNKNOWN",
                "LEASE_WELL_NAME": lease_nm[:80] or "UNKNOWN",
                "CURR_OPERATOR":   operator[:80],
                "ORIG_OPERATOR":   operator[:80],
                "FIELD":           field[:80],
                "COUNTY":          RRC_COUNTY.get(county_c, county_c),
                "STATE":           "TX",
                "COUNTRY":         "US",
                "LATITUDE":        "",
                "LONGITUDE":       "",
                "DEPTH":           td,
                "ELEV_REF":        "KB",
                "SPUD":            spud,
                "COMPLETION":      compl,
                "STATUS":          WELL_STATUS.get(rec_type, "ACTIVE"),
                "SOURCE":          "RRC_TX",
            })

            if limit and len(wells) >= limit:
                break

    print(f"  Parsed {len(wells):,} wells from MAF016")
    return wells


def parse_w1(filepath: str, county_filter: set | None,
             limit: int | None) -> dict[str, tuple[float, float]]:
    """Parse W-1 permits, return {uwi_14: (lat, lon)} lookup."""
    print(f"\nParsing W-1: {filepath}")
    coords: dict[str, tuple[float, float]] = {}
    current: dict = {}

    with open(filepath, encoding="latin-1", errors="replace") as f:
        for line in f:
            if len(line) < 2:
                continue
            rec = line[:2]

            if rec == "01":
                # Save previous
                if current.get("uwi") and current.get("lat"):
                    coords[current["uwi"]] = (current["lat"], current["lon"])
                    if limit and len(coords) >= limit:
                        break
                current = {}
                try:
                    api9     = line[2:11].strip()
                    county_c = line[11:14].strip()
                    if county_filter and county_c not in county_filter:
                        continue
                    fips  = county_c.zfill(3)
                    uwi   = _make_uwi_14(fips, api9[-5:], "0")
                    current = {"uwi": uwi, "lat": None, "lon": None}
                except Exception:
                    pass

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

        if current.get("uwi") and current.get("lat"):
            coords[current["uwi"]] = (current["lat"], current["lon"])

    print(f"  Parsed {len(coords):,} coordinate records from W-1")
    return coords


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Preprocess RRC MAF016 + W-1 → CSV for DataView importer")
    ap.add_argument("--maf016",  required=True, help="Path to MAF016 file")
    ap.add_argument("--w1",      default=None,  help="Path to W-1 permits file")
    ap.add_argument("--county",  default=None,
                    help="RRC county codes to filter (e.g. '130,310,240')")
    ap.add_argument("--limit",   type=int, default=None,
                    help="Max wells to process (for testing)")
    ap.add_argument("--out",     default=None,
                    help="Output CSV path (default: same dir as MAF016 file)")
    args = ap.parse_args()

    # Default output to same directory as MAF016 file
    if args.out is None:
        args.out = "rrc_texas_wells.csv"

    county_filter = None
    if args.county:
        county_filter = {c.strip() for c in args.county.split(",")}

    # Parse MAF016
    wells = parse_maf016(args.maf016, county_filter, args.limit)
    if not wells:
        print("No wells parsed from MAF016")
        return

    # Parse W-1 coordinates if provided
    if args.w1:
        coords = parse_w1(args.w1, county_filter, args.limit)
        matched = 0
        for w in wells:
            c = coords.get(w["API_NUM_NODASH"])
            if c:
                w["LATITUDE"]  = c[0]
                w["LONGITUDE"] = c[1]
                matched += 1
        print(f"\nCoordinate join: {matched:,} / {len(wells):,} wells matched")
    else:
        print("\nNo W-1 file provided — coordinates will be empty")

    # Dedup by UWI
    seen = {}
    for w in wells:
        seen[w["API_NUM_NODASH"]] = w
    wells = list(seen.values())

    # Write CSV
    df = pd.DataFrame(wells)
    df.to_csv(args.out, index=False)
    print(f"\nOutput: {args.out}")
    print(f"  Rows:    {len(df):,}")
    print(f"  Columns: {list(df.columns)}")

    # County summary
    if "COUNTY" in df.columns:
        print("\nCounty breakdown:")
        for county, count in df["COUNTY"].value_counts().head(15).items():
            print(f"  {county:20} {count:,}")

    print(f"\nReady to drag into DataView importer!")


if __name__ == "__main__":
    main()
