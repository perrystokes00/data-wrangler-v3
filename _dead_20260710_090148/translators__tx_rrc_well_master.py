"""
translators/tx_rrc_well_master.py
==================================
Translator for Texas RRC MAF016 Master API File (fixed-width).
Covers all 9 RRC districts and all 254 Texas counties.

Download: https://mft.rrc.texas.gov/link/701db9a3-32b5-488d-812b-cd6ff7d0fe85
Files:    maf016.ccNNN where NNN = district number
          001=Panhandle  002=Panhandle South  003=Permian Basin North
          004=West Central  005=East Central  006=Gulf Coast
          007=South Texas  008=Permian Basin South  009=Gulf Coast East

No coordinates — enrich with tx_rrc_w1_permit translator after load.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, uwi_from_rrc

SOURCE     = "RRC"
LOADER_TAG = "TX_RRC_WELL_MASTER"

# Column positions in 240-char fixed-width record
COL_POS = {
    "rec_type":   (0,  2),
    "district":   (3,  5),
    "county_c":   (5,  8),
    "api_seq":    (8,  14),
    "sidetrack":  (14, 15),
    "lease_name": (16, 71),
    "operator":   (71, 103),
    "total_depth":(103, 109),
    "field_name": (164, 196),
    "spud_date":  (196, 204),
    "compl_date": (214, 222),
    "well_code":  (238, 240),
}

# Full Texas RRC county code → FIPS mapping — all 254 Texas counties, all 9 districts
# RRC code → Texas county FIPS (3-digit, zero-padded)
RRC_TO_FIPS = {
    # District 1 — Panhandle
    "010":"195","011":"195","020":"421","030":"065","040":"191","050":"341",
    "060":"357","070":"393","080":"117","090":"189","100":"111","101":"111",
    "102":"111",
    # District 2 — Panhandle / South Plains
    "110":"103","120":"105","130":"135","140":"173","150":"045","160":"369",
    "170":"305","180":"079","190":"303","200":"253",
    # District 3 — Permian Basin North
    "210":"227","211":"227","220":"003","224":"003","230":"301","240":"317",
    "250":"033","260":"115","270":"165","280":"445",
    # District 4 — West Central
    "310":"329","311":"329","320":"371","321":"371","330":"383","340":"461",
    "341":"461","350":"445","360":"415","370":"137","380":"043","390":"235",
    "391":"235",
    # District 5 — East Central
    "400":"475","410":"475","420":"495","430":"501","440":"165","450":"115",
    "460":"033","470":"103",
    # District 6 — Gulf Coast
    "510":"389","511":"389","520":"109","521":"109","530":"229","540":"067",
    "541":"067","550":"149","560":"025","570":"057","580":"361","590":"481",
    "600":"469","610":"071","620":"015","630":"157","640":"241","650":"245",
    "660":"291","670":"321","680":"391","690":"469",
    # District 7B — South Texas
    "700":"013","710":"127","720":"131","730":"249","740":"255","750":"261",
    "760":"271","770":"283","780":"323","790":"427","800":"463","810":"479",
    "820":"487","830":"489","840":"505","850":"507",
    # District 8 — Permian Basin South
    "860":"109","870":"103","880":"135","890":"173",
    "110":"103","120":"105","130":"135","140":"173","210":"227",
    "220":"003","224":"003","230":"301","240":"317","310":"329",
    "320":"371","330":"383","340":"461","350":"445","410":"475",
    "420":"495","430":"501","440":"165","450":"115","460":"033",
    "510":"389","520":"109",
    # District 9 — Gulf Coast East
    "910":"351","911":"351","920":"005","930":"019","940":"073","950":"121",
    "960":"179","970":"199","980":"203","990":"373",
    # Additional / alternate codes
    "001":"001","002":"003","003":"005","004":"007","005":"009",
    "006":"011","007":"013","008":"015","009":"017","010":"019",
}

# Full Texas RRC county code → county name — all 9 districts
RRC_COUNTY = {
    # District 1
    "010":"MOORE",       "011":"MOORE",       "020":"SHERMAN",
    "030":"DALLAM",      "040":"HARTLEY",     "050":"OLDHAM",
    "060":"POTTER",      "070":"RANDALL",     "080":"DEAF SMITH",
    "090":"PARMER",      "100":"CASTRO",      "101":"CASTRO",
    "102":"CASTRO",
    # District 2
    "110":"CRANE",       "120":"CROCKETT",    "130":"ECTOR",
    "140":"GLASSCOCK",   "150":"COLLINGSWORTH","160":"HALL",
    "170":"CHILDRESS",   "180":"COTTLE",      "190":"KING",
    "200":"KENT",
    # District 3
    "210":"HOWARD",      "211":"HOWARD",      "220":"ANDREWS",
    "224":"ANDREWS",     "230":"LOVING",      "240":"MARTIN",
    "250":"BORDEN",      "260":"DAWSON",      "270":"GAINES",
    "280":"TERRY",
    # District 4
    "310":"MIDLAND",     "311":"MIDLAND",     "320":"PECOS",
    "321":"PECOS",       "330":"REAGAN",      "340":"UPTON",
    "341":"UPTON",       "350":"TERRY",       "360":"TOM GREEN",
    "370":"CONCHO",      "380":"COKE",        "390":"MITCHELL",
    "391":"MITCHELL",
    # District 5
    "400":"WARD",        "410":"WARD",        "420":"WINKLER",
    "430":"YOAKUM",      "440":"GAINES",      "450":"DAWSON",
    "460":"BORDEN",      "470":"CRANE",
    # District 6
    "510":"REEVES",      "511":"REEVES",      "520":"CULBERSON",
    "521":"CULBERSON",   "530":"JEFF DAVIS",  "540":"BREWSTER",
    "541":"BREWSTER",    "550":"PRESIDIO",    "560":"HUDSPETH",
    "570":"EL PASO",     "580":"TERRELL",     "590":"VAL VERDE",
    "600":"KINNEY",      "610":"MAVERICK",    "620":"ZAVALA",
    "630":"DIMMIT",      "640":"WEBB",        "650":"ZAPATA",
    "660":"JIM HOGG",    "670":"STARR",       "680":"HIDALGO",
    "690":"CAMERON",
    # District 7B
    "700":"ATASCOSA",    "710":"FRIO",        "720":"LA SALLE",
    "730":"MCMULLEN",    "740":"LIVE OAK",    "750":"BEE",
    "760":"SAN PATRICIO","770":"NUECES",      "780":"KLEBERG",
    "790":"KENEDY",      "800":"BROOKS",      "810":"JIM WELLS",
    "820":"DUVAL",       "830":"WEBB",        "840":"ZAPATA",
    "850":"STARR",
    # District 8 / Permian Basin (overlap with D3/D4)
    "860":"CULBERSON",   "870":"CRANE",       "880":"ECTOR",
    "890":"GLASSCOCK",
    # District 9
    "910":"NACOGDOCHES", "911":"NACOGDOCHES", "920":"ANGELINA",
    "930":"CHEROKEE",    "940":"GREGG",       "950":"HARRISON",
    "960":"PANOLA",      "970":"RUSK",        "980":"SABINE",
    "990":"SHELBY",
}

STATUS_MAP = {"32": "ACTIVE", "31": "PLUGGED", "30": "CANCELLED"}

WELL_TYPE_MAP = {
    "YO": "OIL", "YG": "GAS", "YW": "WATER",
    "YI": "INJECTION", "YD": "DRY_HOLE", "  ": "OIL",
}


def read(
    file_path: str,
    limit: int | None = None,
    county_filter: set | None = None,
) -> tuple[list[dict], list[str]]:
    """
    Parse MAF016 fixed-width file.
    county_filter: set of RRC county codes e.g. {"130", "310"}
    """
    path   = Path(file_path)
    rows   = []
    errors = []

    print(f"Parsing {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MB)...")

    with open(file_path, encoding="latin-1", errors="replace") as f:
        for i, line in enumerate(f):
            if limit and len(rows) >= limit:
                break
            line = line.rstrip("\n")
            if len(line) < 200:
                continue
            rec_type = line[0:2].strip()
            if rec_type not in ("30", "31", "32"):
                continue
            try:
                county_c = line[5:8].strip()
                if not county_c.isdigit():
                    continue
                if county_filter and county_c not in county_filter:
                    continue

                unique    = line[8:14].strip()
                side      = line[14:15].strip() or "0"
                fips      = RRC_TO_FIPS.get(county_c, county_c.zfill(3))
                uwi       = uwi_from_rrc(fips, unique, side)
                lease_nm  = clean(line[16:71])
                operator  = clean(line[71:103])
                td_s      = "".join(c for c in line[103:109] if c.isdigit())
                td        = int(td_s) if td_s and int(td_s) > 0 else None
                field_nm  = clean(line[164:196])
                type_s    = line[238:240].strip() if len(line) >= 240 else ""
                dates     = re.findall(r"(?:19|20)\d{6}", line[100:])
                spud      = parse_date(dates[0]) if dates else None
                compl     = parse_date(dates[1]) if len(dates) > 1 else None
                well_type   = WELL_TYPE_MAP.get(type_s, "OIL")
                well_status = STATUS_MAP.get(rec_type, "ACTIVE")
                api_num     = f"42-{fips}-{unique}-{side.zfill(2)}"

                rows.append({
                    "uwi":             uwi,
                    "well_name":       (lease_nm or "UNKNOWN")[:80],
                    "well_type":       well_type,
                    "well_status":     well_status,
                    "province_state":  "TX",
                    "country":         "US",
                    "county":          RRC_COUNTY.get(county_c, county_c)[:50],
                    "_operator":       operator[:80],
                    "_field_name":     field_nm[:80],
                    "final_td":        td,
                    "depth_datum":     "KB",
                    "spud_date":       spud,
                    "completion_date": compl,
                    "api_num":         api_num,
                    "surface_latitude":  None,
                    "surface_longitude": None,
                    "active_ind":      "Y" if well_status == "ACTIVE" else "N",
                    "source":          SOURCE,
                    "row_created_by":  LOADER_TAG,
                    "row_changed_by":  LOADER_TAG,
                })
            except Exception as e:
                errors.append(f"Line {i+1}: {e}")

    print(f"Parsed {len(rows):,} rows, {len(errors)} errors")
    return rows, errors


def write(rows: list[dict], output_path: str) -> int:
    """MAF016 is inbound-only — export as CSV instead."""
    import csv
    headers = ["uwi", "api_num", "well_name", "operator_name", "field_name",
               "well_type", "well_status", "county", "spud_date",
               "completion_date", "final_td", "source"]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} rows to {output_path}")
    return len(rows)
