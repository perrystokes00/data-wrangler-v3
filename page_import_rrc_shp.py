"""
page_import_rrc_shp.py — RRC Texas well shapefile loader
=========================================================
Loads RRC Texas county well shapefiles (wellNNNb.shp) directly into
dataview.dv_well. Each shapefile has API numbers and NAD83 coordinates.

Accepts a directory path containing one or more wellNNNb.shp files
(with their companion .dbf/.shx/.prj). Processes all shapefiles found.

Wire into page_dv_importer.py:
    with st.expander("🗺️ 0e · RRC Texas Well Shapefiles", expanded=False):
        try:
            import page_import_rrc_shp
            page_import_rrc_shp.render(engine)
        except Exception as e:
            st.error(f"RRC shapefile loader unavailable: {e}")
"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
from typing import Optional

import streamlit as st


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha1(value: str) -> str:
    return hashlib.sha1(value.upper().strip().encode("utf-8")).hexdigest()

def _trunc(val, n: int) -> Optional[str]:
    if val is None: return None
    s = str(val).strip(); return s[:n] if s else None

def _safe_float(val) -> Optional[float]:
    if val is None or val == "": return None
    try:
        v = float(val)
        return v if v != 0.0 else None  # skip zero coords
    except (TypeError, ValueError): return None


# RRC FIPS county code → county name (common ones for display)
FIPS_COUNTY = {
    "001": "ANDERSON",  "003": "ANDREWS",  "005": "ANGELINA",
    "007": "ARANSAS",   "009": "ARCHER",   "013": "ATASCOSA",
    "015": "AUSTIN",    "017": "BAILEY",   "019": "BANDERA",
    "023": "BAYLOR",    "025": "BEE",      "027": "BELL",
    "029": "BEXAR",     "033": "BORDEN",   "039": "BRAZORIA",
    "041": "BRAZOS",    "049": "BROWN",    "051": "BURLESON",
    "053": "BURNET",    "055": "CALDWELL", "057": "CALHOUN",
    "059": "CALLAHAN",  "061": "CAMERON",  "063": "CAMP",
    "067": "CASS",      "071": "CHAMBERS", "073": "CHEROKEE",
    "077": "CLAY",      "079": "COCHRAN",  "081": "COKE",
    "083": "COLEMAN",   "085": "COLLIN",   "089": "COLORADO",
    "091": "COMAL",     "093": "COMANCHE", "095": "CONCHO",
    "097": "COOKE",     "099": "CORYELL",  "101": "COTTLE",
    "103": "CRANE",     "105": "CROCKETT", "107": "CROSBY",
    "109": "CULBERSON", "111": "DALLAM",   "113": "DALLAS",
    "115": "DAWSON",    "117": "DEAF SMITH","119": "DELTA",
    "121": "DENTON",    "123": "DEWITT",   "127": "DIMMIT",
    "129": "DONLEY",    "131": "DUVAL",    "133": "EASTLAND",
    "135": "ECTOR",     "137": "EDWARDS",  "139": "ELLIS",
    "141": "EL PASO",   "143": "ERATH",    "145": "FALLS",
    "147": "FANNIN",    "149": "FAYETTE",  "151": "FISHER",
    "153": "FLOYD",     "155": "FOARD",    "157": "FORT BEND",
    "159": "FRANKLIN",  "161": "FREESTONE","163": "FRIO",
    "165": "GAINES",    "167": "GALVESTON","169": "GARZA",
    "171": "GILLESPIE", "173": "GLASSCOCK","175": "GOLIAD",
    "177": "GONZALES",  "179": "GRAY",     "181": "GRAYSON",
    "183": "GREGG",     "185": "GRIMES",   "187": "GUADALUPE",
    "189": "HALE",      "191": "HALL",     "193": "HAMILTON",
    "195": "HANSFORD",  "197": "HARDEMAN", "199": "HARDIN",
    "201": "HARRIS",    "203": "HARRISON", "205": "HARTLEY",
    "207": "HASKELL",   "209": "HAYS",     "211": "HEMPHILL",
    "213": "HENDERSON", "215": "HIDALGO",  "217": "HILL",
    "219": "HOCKLEY",   "221": "HOOD",     "223": "HOPKINS",
    "225": "HOUSTON",   "227": "HOWARD",   "229": "HUDSPETH",
    "231": "HUNT",      "233": "HUTCHINSON","235": "IRION",
    "237": "JACK",      "239": "JACKSON",  "241": "JASPER",
    "243": "JEFF DAVIS","245": "JEFFERSON","247": "JIM HOGG",
    "249": "JIM WELLS", "251": "JOHNSON",  "253": "JONES",
    "255": "KARNES",    "257": "KAUFMAN",  "259": "KENDALL",
    "261": "KENEDY",    "263": "KENT",     "265": "KERR",
    "267": "KIMBLE",    "269": "KING",     "271": "KINNEY",
    "273": "KLEBERG",   "275": "KNOX",     "277": "LAMAR",
    "279": "LAMB",      "281": "LAMPASAS", "283": "LASALLE",
    "285": "LAVACA",    "287": "LEE",      "289": "LEON",
    "291": "LIBERTY",   "293": "LIMESTONE","295": "LIPSCOMB",
    "297": "LIVE OAK",  "299": "LLANO",    "301": "LOVING",
    "303": "LUBBOCK",   "305": "LYNN",     "307": "MADISON",
    "309": "MARION",    "311": "MARTIN",   "313": "MASON",
    "315": "MATAGORDA", "317": "MAVERICK", "319": "MCCULLOCH",
    "321": "MCLENNAN",  "323": "MCMULLEN", "325": "MEDINA",
    "327": "MENARD",    "329": "MIDLAND",  "331": "MILAM",
    "333": "MILLS",     "335": "MITCHELL", "337": "MONTAGUE",
    "339": "MONTGOMERY","341": "MOORE",    "343": "MORRIS",
    "345": "MOTLEY",    "347": "NACOGDOCHES","349": "NAVARRO",
    "351": "NEWTON",    "353": "NOLAN",    "355": "NUECES",
    "357": "OCHILTREE", "359": "OLDHAM",   "361": "ORANGE",
    "363": "PALO PINTO","365": "PANOLA",   "367": "PARKER",
    "369": "PARMER",    "371": "PECOS",    "373": "POLK",
    "375": "POTTER",    "377": "PRESIDIO", "379": "RAINS",
    "381": "RANDALL",   "383": "REAGAN",   "385": "REAL",
    "387": "RED RIVER", "389": "REEVES",   "391": "REFUGIO",
    "393": "ROBERTS",   "395": "ROBERTSON","397": "ROCKWALL",
    "399": "RUNNELS",   "401": "RUSK",     "403": "SABINE",
    "405": "SAN AUGUSTINE","407": "SAN JACINTO","409": "SAN PATRICIO",
    "411": "SAN SABA",  "413": "SCHLEICHER","415": "SCURRY",
    "417": "SHACKELFORD","419": "SHELBY",  "421": "SHERMAN",
    "423": "SMITH",     "425": "SOMERVELL","427": "STARR",
    "429": "STEPHENS",  "431": "STERLING", "433": "STONEWALL",
    "435": "SUTTON",    "437": "SWISHER",  "439": "TARRANT",
    "441": "TAYLOR",    "443": "TERRELL",  "445": "TERRY",
    "447": "THROCKMORTON","449": "TITUS",  "451": "TOM GREEN",
    "453": "TRAVIS",    "455": "TRINITY",  "457": "TYLER",
    "459": "UPSHUR",    "461": "UPTON",    "463": "UVALDE",
    "465": "VAL VERDE", "467": "VAN ZANDT","469": "VICTORIA",
    "471": "WALKER",    "473": "WALLER",   "475": "WARD",
    "477": "WASHINGTON","479": "WEBB",     "481": "WHARTON",
    "483": "WHEELER",   "485": "WICHITA",  "487": "WILBARGER",
    "489": "WILLACY",   "491": "WILLIAMSON","493": "WILSON",
    "495": "WINKLER",   "497": "WISE",     "499": "WOOD",
    "501": "YOAKUM",    "503": "YOUNG",    "505": "ZAPATA",
    "507": "ZAVALA",
}


# ══════════════════════════════════════════════════════════════════════════════
# Shapefile reader
# ══════════════════════════════════════════════════════════════════════════════

def read_well_shapefile(shp_path: str) -> list[dict]:
    """Read a single RRC wellNNNb.shp file and return list of well dicts."""
    import geopandas as gpd

    gdf = gpd.read_file(shp_path)
    wells = []

    for _, row in gdf.iterrows():
        apinum = str(row.get("APINUM", "")).strip()
        if not apinum or len(apinum) < 8:
            continue

        # Normalize to 10-digit: state(2) + county(3) + well(5)
        apinum_10 = apinum.zfill(10)[:10]

        # Build 14-digit UWI: pad with 0000 suffix
        uwi_14 = apinum_10 + "0000"

        # Dashed API
        api_dashed = f"{apinum_10[:2]}-{apinum_10[2:5]}-{apinum_10[5:10]}"

        # County from FIPS code in the API
        county_fips = apinum_10[2:5]
        county_name = FIPS_COUNTY.get(county_fips, "")

        # Coordinates — prefer NAD83
        lat = _safe_float(row.get("LAT83"))
        lon = _safe_float(row.get("LONG83"))
        if lat is None or lon is None:
            lat = _safe_float(row.get("LAT27"))
            lon = _safe_float(row.get("LONG27"))

        # Skip wells with no usable coordinates
        if lat is None or lon is None:
            continue

        # Basic validation — Texas bounds
        if not (25.0 <= lat <= 37.0 and -107.0 <= lon <= -93.0):
            continue

        wells.append({
            "uwi":        uwi_14,
            "api_num":    api_dashed,
            "county":     county_name.title() if county_name else "",
            "lat":        lat,
            "lon":        lon,
            "symnum":     row.get("SYMNUM"),
            "reliab":     row.get("RELIAB"),
            "cwellnum":   str(row.get("CWELLNUM", "")).strip(),
        })

    return wells


# ══════════════════════════════════════════════════════════════════════════════
# Database loader
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_source(con, source: str) -> None:
    from sqlalchemy import text
    con.execute(text("""
        MERGE dataview.dv_r_source AS tgt
        USING (SELECT :src AS source) s ON tgt.source = s.source
        WHEN NOT MATCHED THEN INSERT (
            source, short_name, long_name, active_ind,
            row_created_by, row_created_date
        ) VALUES (:src, :src, :long, 'Y', 'RRC_SHP_LOADER', GETUTCDATE());
    """), {"src": _trunc(source, 40),
           "long": _trunc(f"RRC Texas shapefile — {source}", 255)})


def bulk_load_wells(engine, wells: list[dict], source: str,
                    progress_cb=None) -> dict:
    """BULK INSERT wells via CSV → temp table → MERGE into dv_well."""
    from sqlalchemy import text
    stats = {"loaded": 0, "skipped": 0}

    if not wells:
        return stats

    csv_dir = Path(r"C:\temp")
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = str(csv_dir / "rrc_shp_wells.csv")

    with engine.begin() as con:
        _ensure_source(con, source)
        if progress_cb: progress_cb(0.10)

        # Write CSV
        row_count = 0
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_NONE,
                            escapechar="\\")
            for w in wells:
                wr.writerow([
                    _trunc(w["uwi"], 40),
                    _trunc(w.get("api_num"), 20) or "",
                    _trunc(w.get("county"), 100) or "",
                    w.get("lat") or "",
                    w.get("lon") or "",
                ])
                row_count += 1

        if progress_cb: progress_cb(0.30)

        # Temp table + BULK INSERT
        con.execute(text("""
            IF OBJECT_ID('tempdb..#shp') IS NOT NULL DROP TABLE #shp;
            CREATE TABLE #shp (
                uwi     NVARCHAR(40) NOT NULL,
                api_num NVARCHAR(20),
                county  NVARCHAR(100),
                lat     NVARCHAR(30),
                lon     NVARCHAR(30)
            );
        """))

        csv_sql = csv_path.replace("'", "''")
        con.execute(text(f"""
            BULK INSERT #shp FROM '{csv_sql}'
            WITH (FIELDTERMINATOR='\\t', ROWTERMINATOR='\\n',
                  CODEPAGE='65001', TABLOCK);
        """))

        if progress_cb: progress_cb(0.50)

        # MERGE — insert new wells, update coordinates on existing
        con.execute(text("""
            MERGE dataview.dv_well AS tgt
            USING (
                SELECT uwi, api_num, county,
                       TRY_CAST(NULLIF(lat,'') AS FLOAT) AS lat,
                       TRY_CAST(NULLIF(lon,'') AS FLOAT) AS lon
                FROM #shp
            ) AS src ON tgt.uwi = src.uwi
            WHEN NOT MATCHED THEN INSERT (
                uwi, api_num,
                province_state, county, country,
                surface_latitude, surface_longitude,
                active_ind, source,
                row_created_by, row_created_date
            ) VALUES (
                src.uwi, src.api_num,
                'TX', src.county, 'US',
                src.lat, src.lon,
                'Y', :src,
                'RRC_SHP_LOADER', GETUTCDATE()
            )
            WHEN MATCHED THEN UPDATE SET
                surface_latitude  = COALESCE(tgt.surface_latitude, src.lat),
                surface_longitude = COALESCE(tgt.surface_longitude, src.lon),
                county            = COALESCE(tgt.county, src.county),
                api_num           = COALESCE(tgt.api_num, src.api_num),
                row_changed_by    = 'RRC_SHP_LOADER',
                row_changed_date  = GETUTCDATE();
        """), {"src": _trunc(source, 40)})

        stats["loaded"] = row_count
        if progress_cb: progress_cb(0.90)

        con.execute(text("DROP TABLE IF EXISTS #shp;"))

    try: os.unlink(csv_path)
    except Exception: pass

    if progress_cb: progress_cb(1.0)
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# Streamlit render
# ══════════════════════════════════════════════════════════════════════════════

def render(engine) -> None:
    st.caption(
        "Loads RRC Texas county well shapefiles (wellNNNb.shp) into dv_well. "
        "Each shapefile has API numbers and NAD83 coordinates. "
        "Point at a directory containing one or more wellNNNb.shp files."
    )

    dir_path = st.text_input(
        "Directory containing well shapefiles",
        placeholder=r"C:\RRC\shapefiles",
        key="rrc_shp_dir",
        help="Each county is a separate shapefile: well001b.shp, well003b.shp, etc.",
    )

    source_label = st.text_input(
        "Source label", value="RRC_TX_SHP", key="rrc_shp_source")

    if not dir_path.strip():
        st.info("Enter the directory path containing RRC well shapefiles.")
        return

    shp_dir = Path(dir_path.strip())
    if not shp_dir.exists():
        st.error(f"Directory not found: `{dir_path}`")
        return

    # Find all well shapefiles
    shp_files = sorted(shp_dir.glob("well*b.shp"))
    if not shp_files:
        # Try without the 'b' suffix
        shp_files = sorted(shp_dir.glob("well*.shp"))
    if not shp_files:
        st.warning(f"No well*.shp files found in `{dir_path}`")
        return

    st.info(f"Found **{len(shp_files)}** shapefile(s): "
            + ", ".join(f.stem for f in shp_files[:10])
            + ("…" if len(shp_files) > 10 else ""))

    # State machine
    _cache_key = f"rrc_shp|{dir_path}|{source_label}"
    if st.session_state.get("_shp_key") != _cache_key:
        st.session_state.pop("_shp_wells", None)
        st.session_state.pop("_shp_stats", None)
        st.session_state["_shp_key"] = _cache_key

    wells = st.session_state.get("_shp_wells")
    stats = st.session_state.get("_shp_stats")

    # ── IDLE: Parse button ────────────────────────────────────────────
    if wells is None:
        if not st.button("🔍 Parse & Preview", type="primary",
                         key="rrc_shp_parse_btn",
                         use_container_width=True):
            return

        try:
            import geopandas  # noqa: check available
        except ImportError:
            st.error("geopandas is required: `pip install geopandas`")
            return

        all_wells = []
        prog = st.progress(0.0, text="Reading shapefiles…")
        for i, shp in enumerate(shp_files):
            prog.progress(i / len(shp_files),
                          text=f"Reading {shp.name}…")
            try:
                batch = read_well_shapefile(str(shp))
                all_wells.extend(batch)
            except Exception as e:
                st.warning(f"Skipped {shp.name}: {e}")

        prog.empty()

        if not all_wells:
            st.warning("No wells with coordinates found in the shapefiles.")
            return

        # Dedup by UWI
        seen = {}
        for w in all_wells:
            seen[w["uwi"]] = w
        all_wells = list(seen.values())

        st.session_state["_shp_wells"] = all_wells
        st.rerun()

    # ── DONE: show results ────────────────────────────────────────────
    if stats is not None:
        if stats["skipped"] == 0:
            st.success(f"✅ Loaded {stats['loaded']:,} wells with coordinates.")
        else:
            st.warning(
                f"✅ Loaded {stats['loaded']:,} wells · "
                f"⚠️ {stats['skipped']:,} skipped")
        if st.button("🔄 Reset", key="rrc_shp_reset"):
            st.session_state.pop("_shp_wells", None)
            st.session_state.pop("_shp_stats", None)
            st.rerun()
        return

    # ── PARSED: preview + load ────────────────────────────────────────
    import pandas as pd

    # County summary
    county_counts = {}
    for w in wells:
        c = w.get("county") or "Unknown"
        county_counts[c] = county_counts.get(c, 0) + 1

    m1, m2 = st.columns(2)
    m1.metric("Total wells with coordinates", f"{len(wells):,}")
    m2.metric("Counties", f"{len(county_counts):,}")

    if len(county_counts) <= 20:
        st.caption("County breakdown: " +
                   " · ".join(f"{c}: {n:,}" for c, n in
                              sorted(county_counts.items(),
                                     key=lambda x: -x[1])))

    df = pd.DataFrame(wells)
    st.dataframe(df.head(50), use_container_width=True, hide_index=True)
    if len(wells) > 50:
        st.caption(f"Showing 50 of {len(wells):,} rows.")

    if not st.button("🚀 Load into DataView", type="primary",
                     key="rrc_shp_load_btn",
                     use_container_width=True):
        return

    # ── LOADING ───────────────────────────────────────────────────────
    src = (source_label or "RRC_TX_SHP").strip()
    prog = st.progress(0.0, text=f"Loading {len(wells):,} wells…")
    try:
        result = bulk_load_wells(engine, wells, src,
                                 progress_cb=lambda p: prog.progress(p))
    except Exception as e:
        st.error(f"Load failed: {type(e).__name__}: {e}")
        prog.empty()
        return

    prog.empty()
    st.session_state["_shp_stats"] = result
    st.rerun()
