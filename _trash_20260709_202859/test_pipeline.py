"""
test_pipeline.py — regression guard for the DataView extract/catalog pipeline.

Run this BEFORE and AFTER any refactoring step. Green = behavior unchanged.
It pins the known-good results established on 2026-06-26 for three OCR'd
Permian scout tickets, exercising each layer of the pipeline independently so a
break is localized to the layer that fails.

Layers tested, in pipeline order:
  1. extract_scout_ticket   — grid extractor: all 8 sections + GID→bare-14 UWI
  2. extract_core._extract_fields — the PIPELINE's field/UWI resolver
  3. catalog_rules.extract_file_fields + score_file — scoring path → READY
  4. page_workbench._load_rows_to_catalog — capture writer → cat_* row counts
     (DB layer; only runs when --db is passed and a connection succeeds)

Usage:
    python test_pipeline.py            # layers 1-3 (no DB needed)
    python test_pipeline.py --db       # all layers incl. capture into cat_*

Set PDF_DIR below to wherever the three _OCR.pdf test files live.
"""
from __future__ import annotations
import os
import sys
import traceback

# --- where the three known test PDFs live (adjust if they move) -------------
PDF_DIR = os.environ.get(
    "DV_TEST_PDF_DIR",
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler"
    r"\training\test_crawl_3\pdf")

DB_NAME = os.environ.get("DV_TEST_DB", "DataView_Demo")

# --- the known-good expectations (captured 2026-06-26) ----------------------
WELLS = {
    "42462000120000_OCR.pdf": {
        "uwi": "42423000120000", "well_name": "STATE WAR 012",
        "operator": "Devon Energy", "status": "ACTIVE",
        "tops": 3, "survey": 15, "dst": 0, "frac": 0,
        "core": 4, "production": 12, "completion": 0,
        "load_rows": 11,            # no DST/frac/completion
    },
    "42330000350000_OCR.pdf": {
        "uwi": "42232000350000", "well_name": "STATE MAR 035H",
        "operator": "Devon Energy", "status": "ACTIVE",
        "tops": 3, "survey": 15, "dst": 1, "frac": 15,
        "core": 4, "production": 12, "completion": 1,
        "load_rows": 27,            # full ticket
        "lat": "32.127700", "lon": "-101.560500",   # the OCR-slash-bug well
    },
    "42395000130000_OCR.pdf": {
        "uwi": "42342000130000", "well_name": "STATE AND 013H",
        "operator": "Coterra Energy", "status": "ABANDONED",
        "tops": 3, "survey": 15, "dst": 0, "frac": 15,
        "core": 4, "production": 12, "completion": 1,
        "load_rows": 26,
    },
}

# --- tiny test framework ----------------------------------------------------
_passed = 0
_failed = 0
_fails: list[str] = []


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {label}: {got!r}")
    else:
        _failed += 1
        msg = f"  FAIL  {label}: got {got!r}, expected {want!r}"
        print(msg)
        _fails.append(msg)


def _path(fname):
    return os.path.join(PDF_DIR, fname)


# --- Layer 1: grid extractor ------------------------------------------------
def test_extract_scout_ticket():
    print("\n[1] extract_scout_ticket — grid extraction, all sections")
    from modules.pdf_survey_catalog import extract_scout_ticket
    for fname, exp in WELLS.items():
        print(f"  -- {fname}")
        sc = extract_scout_ticket(_path(fname))
        h = sc.get("header") or {}
        check(f"{fname} uwi", h.get("UWI_BARE14"), exp["uwi"])
        check(f"{fname} well_name", h.get("WELL_NAME"), exp["well_name"])
        check(f"{fname} operator", h.get("OPERATOR"), exp["operator"])
        check(f"{fname} tops", len(sc.get("tops") or []), exp["tops"])
        check(f"{fname} survey", len(sc.get("survey") or []), exp["survey"])
        check(f"{fname} dst", len(sc.get("dst") or []), exp["dst"])
        check(f"{fname} frac", len(sc.get("frac") or []), exp["frac"])
        check(f"{fname} core", len(sc.get("core") or []), exp["core"])
        check(f"{fname} production",
              len(sc.get("ip_rows") or []), exp["production"])
        if "lat" in exp:
            check(f"{fname} lat", h.get("LATITUDE"), exp["lat"])
            check(f"{fname} lon", h.get("LONGITUDE"), exp["lon"])


# --- Layer 2: the pipeline's field resolver ---------------------------------
def test_extract_core_fields():
    print("\n[2] extract_core._extract_fields — pipeline UWI resolution")
    from extract_core import _extract_fields
    for fname, exp in WELLS.items():
        f = _extract_fields(_path(fname), ".pdf")
        check(f"{fname} uwi", f.get("uwi"), exp["uwi"])
        check(f"{fname} report_type", f.get("report_type"), "SCOUT_TICKET")
        check(f"{fname} well_name", f.get("well_name"), exp["well_name"])


# --- Layer 2b: LAS extraction (canonical identity + curve details) ----------
_SAMPLE_LAS = """~Version
VERS. 2.0 : CWLS log ASCII Standard -VERSION 2.0
WRAP.  NO : ONE LINE PER DEPTH STEP
~Well
UWI   . 17-031-10035-0000 : UNIQUE WELL IDENTIFIER
WELL  . DIAMONDB DE S 035 : WELL NAME
FLD   .          WOODFORD : FIELD / FORMATION
SRVC  .       HALLIBURTON : SERVICE COMPANY
DATE  .        2020-05-05 : LOG DATE
STRT  .M       1542.60000 : START DEPTH
STOP  .M       1572.92760 : STOP DEPTH
STEP  .M          0.15240 : STEP
NULL  .           -999.25 : NULL VALUE
CNTY  .              Cook : COUNTY
STAT  .                IL : STATE
CTRY  .                US : COUNTRY
LAT   .         42.158635 : LATITUDE
LONG  .       -101.302573 : LONGITUDE
TYPE  .               LWD : LOG TYPE
LOG_ID.           WL10035 : LOG ID
~Curve Information
DEPT.M     : DEPTH
GR  .GAPI  : Gamma Ray
RHOB.G/CC  : Bulk Density
NPHI.V/V   : Neutron Porosity
RT  .OHMM  : True Resistivity
AZIM.DEG   : Azimuth
INCL.DEG   : Inclination
"""


def test_extract_core_las():
    print("\n[2b] extract_core._extract_fields — LAS identity + curve details")
    import tempfile
    from extract_core import _extract_fields
    tf = os.path.join(tempfile.gettempdir(), "dv_test_sample.las")
    with open(tf, "w") as fh:
        fh.write(_SAMPLE_LAS)
    f = _extract_fields(tf, ".las")
    check("las uwi",         f.get("uwi"),         "17031100350000")
    check("las well_name",   f.get("well_name"),   "DIAMONDB DE S 035")
    check("las well_field",  f.get("well_field"),  "WOODFORD")
    check("las state",       f.get("state"),       "IL")
    check("las county",      f.get("county"),      "Cook")
    check("las latitude",    f.get("latitude"),    "42.158635")
    check("las longitude",   f.get("longitude"),   "-101.302573")
    check("las total_depth", f.get("total_depth"), "1572.9276")
    check("las contractor",  f.get("contractor"),  "HALLIBURTON")
    check("las report_type", f.get("report_type"), "WELL_LOG")
    d = f.get("details") or {}
    check("las details.curves",      d.get("curves"),      7)
    check("las details.depth_start", d.get("depth_start"), "1542.6")
    check("las details.depth_stop",  d.get("depth_stop"),  "1572.9276")


# --- Layer 3: scoring → READY ----------------------------------------------
def test_score_file():
    print("\n[3] catalog_rules.score_file — readiness scoring")
    try:
        import modules.catalog_rules as cr
    except ImportError:
        import catalog_rules as cr
    # simulate "UWI not yet in dv_well" so we test the new-well path
    _orig = cr.match_uwi
    cr.match_uwi = lambda e, u: None
    try:
        for fname, exp in WELLS.items():
            f = cr.extract_file_fields(_path(fname))
            s = cr.score_file(f, engine="FAKE")
            check(f"{fname} matched_uwi", s.get("matched_uwi"), exp["uwi"])
            check(f"{fname} readiness", s.get("readiness"), "READY")
    finally:
        cr.match_uwi = _orig


# --- Layer 4: capture writer (DB) ------------------------------------------
def test_load_to_catalog(engine, dialect="mssql"):
    print("\n[4] _load_rows_to_catalog — capture into cat_* (DB)")
    from page_workbench import _load_rows_to_catalog
    for fname, exp in WELLS.items():
        r = _load_rows_to_catalog(engine, dialect, _path(fname),
                                  ".pdf", exp["uwi"], [])
        check(f"{fname} loaded", r.get("loaded"), exp["load_rows"])
        check(f"{fname} errors", r.get("errors") or [], [])


# --- runner -----------------------------------------------------------------
def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    use_db = "--db" in sys.argv

    if not os.path.isdir(PDF_DIR):
        print(f"!! PDF_DIR not found: {PDF_DIR}")
        print("   Set DV_TEST_PDF_DIR or edit PDF_DIR at the top of this file.")
        return 2

    for layer in (test_extract_scout_ticket,
                  test_extract_core_fields,
                  test_extract_core_las,
                  test_score_file):
        try:
            layer()
        except Exception:
            global _failed
            _failed += 1
            print(f"  ERROR in {layer.__name__}:")
            traceback.print_exc()

    if use_db:
        try:
            from modules.db import connect, DBConfig
            cr = connect(DBConfig(database=DB_NAME))
            test_load_to_catalog(cr.engine)
        except Exception:
            print("  ERROR setting up DB / running capture test:")
            traceback.print_exc()
    else:
        print("\n[4] skipped (pass --db to run capture into cat_*)")

    print("\n" + "=" * 60)
    print(f"  {_passed} passed, {_failed} failed")
    if _fails:
        print("  failures:")
        for m in _fails:
            print("   " + m.strip())
    print("=" * 60)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
