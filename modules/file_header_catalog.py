"""
modules/file_header_catalog.py
===============================
Header snapshot catalog for File Inventory Governance.

Stores the raw decoded header text for each file — no complex parsing,
no JSON blobs, no column mapping gymnastics.

Tables:
  file_catalog.FILE_HEADER  -- one row per file (key fields + raw header text)
  file_catalog.FILE_CURVE   -- one row per curve/channel (mnemonic, unit, descr)

Export produces:
  - Raw header text file per file type
  - CSV/Excel of key fields for pipeline import
  - PPDM comparison report
"""

import hashlib
import datetime
from pathlib import Path
from sqlalchemy import text


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fhid(file_path: str) -> str:
    return hashlib.sha1(file_path.encode("utf-8", errors="replace")).hexdigest()[:40]

def _cid(fhid: str, idx: int) -> str:
    return hashlib.sha1(f"{fhid}{idx}".encode()).hexdigest()[:40]

def _now(dialect: str) -> str:
    return {"mssql": "GETDATE()", "oracle": "SYSTIMESTAMP",
            "snowflake": "CURRENT_TIMESTAMP()"}.get(dialect, "GETDATE()")

def _tbl(dialect: str, name: str) -> str:
    if dialect == "oracle":    return f"FILE_CATALOG_{name}"
    if dialect == "snowflake": return f'"FILE_CATALOG"."{name}"'
    return f"file_catalog.{name}"


# ─────────────────────────────────────────────────────────────────────────────
# DDL — simple and clean
# ─────────────────────────────────────────────────────────────────────────────

DDL_SQLSERVER = """
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='file_catalog')
    EXEC('CREATE SCHEMA file_catalog');

IF NOT EXISTS (SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id=s.schema_id
    WHERE s.name='file_catalog' AND t.name='FILE_HEADER')
CREATE TABLE file_catalog.FILE_HEADER (
    FILE_HEADER_ID   NVARCHAR(40)   NOT NULL PRIMARY KEY,
    INVENTORY_ID     NVARCHAR(64)   NULL,
    FILE_TYPE        NVARCHAR(10)   NOT NULL,
    FILE_PATH        NVARCHAR(900)  NOT NULL,
    FILE_NAME        NVARCHAR(260)  NOT NULL,
    FILE_SIZE_KB     DECIMAL(15,2)  NULL,
    MATCHED_UWI      NVARCHAR(40)   NULL,
    MATCH_METHOD     NVARCHAR(20)   NULL,
    MATCH_SCORE      DECIMAL(5,2)   NULL,
    WELL_NAME        NVARCHAR(200)  NULL,
    HEADER_TEXT      NVARCHAR(MAX)  NULL,
    CATALOGED_BY     NVARCHAR(64)   NULL,
    CATALOG_DATE     DATETIME2      NULL    DEFAULT GETDATE(),
    ACTIVE_IND       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    SOURCE           NVARCHAR(100)  NULL
);

IF NOT EXISTS (SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id=s.schema_id
    WHERE s.name='file_catalog' AND t.name='FILE_CURVE')
CREATE TABLE file_catalog.FILE_CURVE (
    FILE_CURVE_ID    NVARCHAR(40)   NOT NULL PRIMARY KEY,
    FILE_HEADER_ID   NVARCHAR(40)   NOT NULL,
    MNEMONIC         NVARCHAR(40)   NOT NULL,
    UNIT             NVARCHAR(40)   NULL,
    DESCRIPTION      NVARCHAR(200)  NULL,
    SORT_ORDER       INT            NULL,
    CONSTRAINT FK_FC_FH FOREIGN KEY (FILE_HEADER_ID)
        REFERENCES file_catalog.FILE_HEADER(FILE_HEADER_ID)
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='FH_UWI_IDX')
    CREATE INDEX FH_UWI_IDX  ON file_catalog.FILE_HEADER (MATCHED_UWI);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='FH_TYPE_IDX')
    CREATE INDEX FH_TYPE_IDX ON file_catalog.FILE_HEADER (FILE_TYPE);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='FH_INV_IDX')
    CREATE INDEX FH_INV_IDX  ON file_catalog.FILE_HEADER (INVENTORY_ID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='FC_HDR_IDX')
    CREATE INDEX FC_HDR_IDX  ON file_catalog.FILE_CURVE  (FILE_HEADER_ID);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='FC_MNM_IDX')
    CREATE INDEX FC_MNM_IDX  ON file_catalog.FILE_CURVE  (MNEMONIC);
"""

DDL_ORACLE = """
BEGIN
    BEGIN EXECUTE IMMEDIATE '
        CREATE TABLE FILE_CATALOG_FILE_HEADER (
            FILE_HEADER_ID  VARCHAR2(40)   NOT NULL PRIMARY KEY,
            INVENTORY_ID    VARCHAR2(64),
            FILE_TYPE       VARCHAR2(10)   NOT NULL,
            FILE_PATH       VARCHAR2(900)  NOT NULL,
            FILE_NAME       VARCHAR2(260)  NOT NULL,
            FILE_SIZE_KB    NUMBER(15,2),
            MATCHED_UWI     VARCHAR2(40),
            MATCH_METHOD    VARCHAR2(20),
            MATCH_SCORE     NUMBER(5,2),
            WELL_NAME       VARCHAR2(200),
            HEADER_TEXT     CLOB,
            CATALOGED_BY    VARCHAR2(64),
            CATALOG_DATE    TIMESTAMP      DEFAULT SYSTIMESTAMP,
            ACTIVE_IND      VARCHAR2(1)    DEFAULT ''Y'' NOT NULL,
            SOURCE          VARCHAR2(100)
        )';
    EXCEPTION WHEN OTHERS THEN IF SQLCODE!=-955 THEN RAISE; END IF; END;
    BEGIN EXECUTE IMMEDIATE '
        CREATE TABLE FILE_CATALOG_FILE_CURVE (
            FILE_CURVE_ID   VARCHAR2(40)  NOT NULL PRIMARY KEY,
            FILE_HEADER_ID  VARCHAR2(40)  NOT NULL,
            MNEMONIC        VARCHAR2(40)  NOT NULL,
            UNIT            VARCHAR2(40),
            DESCRIPTION     VARCHAR2(200),
            SORT_ORDER      NUMBER(10)
        )';
    EXCEPTION WHEN OTHERS THEN IF SQLCODE!=-955 THEN RAISE; END IF; END;
END;
"""

DDL_SNOWFLAKE = """
CREATE SCHEMA IF NOT EXISTS FILE_CATALOG;
CREATE TABLE IF NOT EXISTS FILE_CATALOG.FILE_HEADER (
    FILE_HEADER_ID   VARCHAR(40)    NOT NULL PRIMARY KEY,
    INVENTORY_ID     VARCHAR(64),
    FILE_TYPE        VARCHAR(10)    NOT NULL,
    FILE_PATH        VARCHAR(900)   NOT NULL,
    FILE_NAME        VARCHAR(260)   NOT NULL,
    FILE_SIZE_KB     DECIMAL(15,2),
    MATCHED_UWI      VARCHAR(40),
    MATCH_METHOD     VARCHAR(20),
    MATCH_SCORE      DECIMAL(5,2),
    WELL_NAME        VARCHAR(200),
    HEADER_TEXT      VARCHAR(16777216),
    CATALOGED_BY     VARCHAR(64),
    CATALOG_DATE     TIMESTAMP_NTZ  DEFAULT CURRENT_TIMESTAMP(),
    ACTIVE_IND       VARCHAR(1)     NOT NULL DEFAULT 'Y',
    SOURCE           VARCHAR(100)
);
CREATE TABLE IF NOT EXISTS FILE_CATALOG.FILE_CURVE (
    FILE_CURVE_ID    VARCHAR(40)    NOT NULL PRIMARY KEY,
    FILE_HEADER_ID   VARCHAR(40)    NOT NULL,
    MNEMONIC         VARCHAR(40)    NOT NULL,
    UNIT             VARCHAR(40),
    DESCRIPTION      VARCHAR(200),
    SORT_ORDER       INT
);
"""


def ensure_header_schema(engine, dialect: str):
    ddl = {"mssql": DDL_SQLSERVER, "oracle": DDL_ORACLE,
           "snowflake": DDL_SNOWFLAKE}.get(dialect, DDL_SQLSERVER)
    with engine.begin() as conn:
        if dialect == "oracle":
            conn.execute(text(ddl))
        else:
            for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# Raw header extraction — text only, no complex parsing
# ─────────────────────────────────────────────────────────────────────────────

def _extract_las(file_path: str) -> tuple[str, str, list]:
    """
    Returns (header_text, well_name, curves).
    header_text = everything before ~A section.
    curves = [{mnemonic, unit, description}]
    """
    with open(file_path, "r", errors="replace") as f:
        raw = f.read()

    # Split at ~A (data section)
    a_idx = raw.upper().find("\n~A")
    header_text = raw[:a_idx].strip() if a_idx > 0 else raw

    # Extract well name and curves from text — simple line scan, no lasio
    well_name = ""
    curves = []
    in_well = False
    in_curve = False

    for line in header_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        upper = stripped.upper()
        if upper.startswith("~W"):
            in_well, in_curve = True, False
            continue
        if upper.startswith("~C"):
            in_well, in_curve = False, True
            continue
        if upper.startswith("~"):
            in_well, in_curve = False, False
            continue

        if in_well or in_curve:
            # Parse mnemonic.unit  value : description
            dot = stripped.find(".")
            colon = stripped.find(":")
            if dot > 0:
                mnem = stripped[:dot].strip().upper()
                rest = stripped[dot+1:]
                sp   = rest.find(" ")
                unit = rest[:sp].strip() if sp > 0 else ""
                desc = stripped[colon+1:].strip() if colon > 0 else ""
                val  = rest[sp:colon].strip() if (sp > 0 and colon > sp) else ""

                if in_well and mnem in ("WELL","WELLNAME","WELL_NAME"):
                    well_name = val
                if in_curve and mnem and mnem not in ("DEPT","DEPTH","MD","TVD"):
                    curves.append({"mnemonic": mnem, "unit": unit,
                                   "description": desc})

    return header_text, well_name, curves


def _extract_dlis(file_path: str) -> tuple[str, str, list]:
    """Decode DLIS binary to readable text."""
    import warnings
    lines = []
    well_name = ""
    curves = []
    try:
        from dlisio import dlis
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with dlis.load(file_path) as lfs:
                for lf_idx, lf in enumerate(lfs):
                    lines.append(f"=== Logical File {lf_idx+1} ===")
                    for o in lf.origins:
                        if not well_name:
                            well_name = str(getattr(o,"well_name","") or "")
                        for attr in ("well_name","well_id","field_name","company",
                                     "country","creation_time","producer_name","run_nr"):
                            v = getattr(o, attr, None)
                            if v: lines.append(f"  {attr:<20s}: {v}")
                    ch_list = list(lf.channels)
                    lines.append(f"\nChannels ({len(ch_list)}):")
                    for ch in ch_list:
                        lines.append(f"  {ch.name:<20s} {str(ch.units or '—'):<10s}"
                                     f" dim={ch.dimension}")
                        curves.append({"mnemonic": ch.name,
                                       "unit": str(ch.units or ""),
                                       "description": ""})
                    params = list(lf.parameters)
                    if params:
                        lines.append(f"\nParameters ({min(len(params),50)}):")
                        for p in params[:50]:
                            lines.append(f"  {p.name:<20s} = {p.values}")
    except Exception as e:
        lines.append(f"Error decoding DLIS: {e}")
    return "\n".join(lines), well_name, curves


def _extract_lis(file_path: str) -> tuple[str, str, list]:
    """Decode LIS binary to readable text."""
    import warnings
    lines = []
    well_name = ""
    curves = []
    try:
        from dlisio import lis
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with lis.load(file_path) as lfs:
                lf = lfs[0]
                lines.append("=== Wellsite Data ===")
                for rec in lf.wellsite_data():
                    for c in rec.components():
                        mnem = str(getattr(c,"mnemonic","")).strip()
                        val  = str(getattr(c,"component","")).strip()
                        if mnem:
                            lines.append(f"  {mnem:<12s} = {val}")
                            if mnem in ("WN","WELL","WELL_NAME") and val:
                                well_name = val
                specs = lf.data_format_specs()
                if specs:
                    lines.append(f"\n=== Curves ===")
                    for i, spec in enumerate(specs):
                        for j, ch in enumerate(spec.entries):
                            mnem  = str(getattr(ch,"mnemonic","?")).strip()
                            unit  = str(getattr(ch,"units","")).strip()
                            lines.append(f"  {mnem:<12s} {unit}")
                            if j > 0:  # skip depth channel
                                curves.append({"mnemonic": mnem,
                                               "unit": unit,
                                               "description": ""})
    except Exception as e:
        lines.append(f"Error decoding LIS: {e}")
    return "\n".join(lines), well_name, curves


def _extract_segy(file_path: str) -> tuple[str, str, list]:
    """Decode SEG-Y EBCDIC header to text."""
    well_name = ""
    try:
        import segyio
        with segyio.open(file_path, ignore_geometry=True) as f:
            ebcdic = f.text[0].decode("cp037", errors="replace")
            lines  = [ebcdic[i:i+80].rstrip() for i in range(0, len(ebcdic), 80)]
            # Binary header key fields
            b = dict(f.bin)
            lines.append("\n--- Binary Header ---")
            for k, v in b.items():
                if int(v) != 0:
                    lines.append(f"  {str(k):<30s}: {int(v)}")
        import re
        for pat in [r"(?i)well[:\s]+([A-Z0-9_\-]+)",
                    r"(?i)line[:\s]+([A-Z0-9_\-]+)"]:
            m = re.search(pat, "\n".join(lines))
            if m:
                well_name = m.group(1).strip()[:200]
                break
        return "\n".join(lines), well_name, []
    except ImportError:
        pass
    try:
        from modules.segy_catalog import parse_segy_header
        hdr = parse_segy_header(file_path)
        text_lines = [f"{k:<30s}: {v}" for k, v in hdr.items() if v]
        well_name  = str(hdr.get("survey_name",""))
        return "\n".join(text_lines), well_name, []
    except Exception as e:
        return f"Error reading SEG-Y: {e}", "", []


def _extract_p190(file_path: str) -> tuple[str, str, list]:
    """Read P190 H-record header lines."""
    well_name = ""
    try:
        with open(file_path, "r", errors="replace") as f:
            lines = f.readlines()
        h_lines = [l.rstrip() for l in lines if l.startswith("H")]
        # Try to find well/survey name from H records
        for l in h_lines:
            code = l[1:3].strip() if len(l) > 2 else ""
            val  = l[3:].strip() if len(l) > 3 else ""
            if code in ("WN","NA","SN") and val:
                well_name = val[:200]
                break
        return "\n".join(h_lines) if h_lines else "".join(lines[:200]), well_name, []
    except Exception as e:
        return f"Error reading P190: {e}", "", []


def extract_header(file_path: str) -> dict:
    """
    Dispatch to correct extractor based on extension.
    Returns dict with: file_type, header_text, well_name, curves
    """
    ext = Path(file_path).suffix.lower()
    dispatch = {
        ".las":  ("LAS",  _extract_las),
        ".dlis": ("DLIS", _extract_dlis),
        ".dlf":  ("DLIS", _extract_dlis),
        ".dis":  ("DLIS", _extract_dlis),
        ".lis":  ("LIS",  _extract_lis),
        ".segy": ("SEGY", _extract_segy),
        ".sgy":  ("SEGY", _extract_segy),
        ".seg":  ("SEGY", _extract_segy),
        ".p190": ("P190", _extract_p190),
        ".p1":   ("P190", _extract_p190),
        ".p90":  ("P190", _extract_p190),
        ".pa90": ("P190", _extract_p190),
    }
    file_type, fn = dispatch.get(ext, ("OTHER", lambda p: ("", "", [])))
    header_text, well_name, curves = fn(file_path)
    return {"file_type": file_type, "header_text": header_text,
            "well_name": well_name, "curves": curves}


# ─────────────────────────────────────────────────────────────────────────────
# Write to DB — single transaction, fast
# ─────────────────────────────────────────────────────────────────────────────

def catalog_file_header(engine, dialect: str, file_path: str,
                         inventory_id: str,
                         matched_uwi: str, match_method: str,
                         match_score: float,
                         guessed_uwi: str, guessed_well: str,
                         guessed_survey: str,
                         cataloged_by: str,
                         file_size_kb: float = None) -> str:
    """
    Extract header text and write FILE_HEADER + FILE_CURVE.
    Returns FILE_HEADER_ID. Upserts — safe to call repeatedly.
    """
    fhid = _fhid(file_path)
    hdr  = extract_header(file_path)
    ht   = _tbl(dialect, "FILE_HEADER")
    ct   = _tbl(dialect, "FILE_CURVE")
    ne   = _now(dialect)

    well_name = hdr["well_name"] or guessed_well or ""

    row = {
        "fhid":    fhid,
        "inv_id":  inventory_id,
        "ftype":   hdr["file_type"],
        "fpath":   file_path,
        "fname":   Path(file_path).name,
        "fsize":   file_size_kb,
        "uwi":     matched_uwi or "",
        "method":  match_method or "",
        "score":   match_score,
        "wname":   well_name[:200] if well_name else "",
        "htext":   hdr["header_text"],
        "cat_by":  cataloged_by,
        "source":  "File Inventory",
    }

    with engine.begin() as conn:
        if dialect == "mssql":
            conn.execute(text(f"""
                MERGE {ht} AS tgt
                USING (SELECT :fhid AS FILE_HEADER_ID) src
                ON tgt.FILE_HEADER_ID = src.FILE_HEADER_ID
                WHEN MATCHED THEN UPDATE SET
                    MATCHED_UWI=:uwi, MATCH_METHOD=:method,
                    MATCH_SCORE=:score, WELL_NAME=:wname,
                    HEADER_TEXT=:htext, CATALOGED_BY=:cat_by,
                    CATALOG_DATE={ne}, ACTIVE_IND='Y'
                WHEN NOT MATCHED THEN INSERT (
                    FILE_HEADER_ID,INVENTORY_ID,FILE_TYPE,FILE_PATH,FILE_NAME,
                    FILE_SIZE_KB,MATCHED_UWI,MATCH_METHOD,MATCH_SCORE,
                    WELL_NAME,HEADER_TEXT,CATALOGED_BY,CATALOG_DATE,
                    ACTIVE_IND,SOURCE
                ) VALUES (
                    :fhid,:inv_id,:ftype,:fpath,:fname,
                    :fsize,:uwi,:method,:score,
                    :wname,:htext,:cat_by,{ne},
                    'Y',:source
                );
            """), row)
        else:
            conn.execute(text(f"DELETE FROM {ht} WHERE FILE_HEADER_ID=:fhid"),
                         {"fhid": fhid})
            conn.execute(text(f"""
                INSERT INTO {ht} (
                    FILE_HEADER_ID,INVENTORY_ID,FILE_TYPE,FILE_PATH,FILE_NAME,
                    FILE_SIZE_KB,MATCHED_UWI,MATCH_METHOD,MATCH_SCORE,
                    WELL_NAME,HEADER_TEXT,CATALOGED_BY,CATALOG_DATE,
                    ACTIVE_IND,SOURCE
                ) VALUES (
                    :fhid,:inv_id,:ftype,:fpath,:fname,
                    :fsize,:uwi,:method,:score,
                    :wname,:htext,:cat_by,{ne},
                    'Y',:source
                )
            """), row)

        # Curves — delete + reinsert
        conn.execute(text(f"DELETE FROM {ct} WHERE FILE_HEADER_ID=:fhid"),
                     {"fhid": fhid})
        curve_rows = [
            {"cid":  _cid(fhid, i),
             "fhid": fhid,
             "mnem": c["mnemonic"][:40],
             "unit": (c.get("unit","") or "")[:40],
             "desc": (c.get("description","") or "")[:200],
             "sort": i}
            for i, c in enumerate(hdr.get("curves", []))
        ]
        if curve_rows:
            conn.execute(text(f"""
                INSERT INTO {ct}
                    (FILE_CURVE_ID,FILE_HEADER_ID,MNEMONIC,UNIT,DESCRIPTION,SORT_ORDER)
                VALUES (:cid,:fhid,:mnem,:unit,:desc,:sort)
            """), curve_rows)

    return fhid


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

def get_catalog_headers(engine, dialect: str,
                         file_type: str = None,
                         uwi: str = None,
                         well_name: str = None) -> "pd.DataFrame":
    """Query FILE_HEADER with curve list."""
    import pandas as pd
    ht = _tbl(dialect, "FILE_HEADER")
    ct = _tbl(dialect, "FILE_CURVE")

    conditions = ["h.ACTIVE_IND='Y'"]
    params: dict = {}
    if file_type:
        conditions.append("h.FILE_TYPE=:ftype"); params["ftype"] = file_type
    if uwi:
        conditions.append("h.MATCHED_UWI LIKE :uwi"); params["uwi"] = f"%{uwi}%"
    if well_name:
        conditions.append("h.WELL_NAME LIKE :wn"); params["wn"] = f"%{well_name}%"
    where = " AND ".join(conditions)

    if dialect == "mssql":
        sql = f"""
            SELECT h.FILE_HEADER_ID, h.FILE_TYPE, h.MATCHED_UWI, h.WELL_NAME,
                   h.MATCH_METHOD, h.MATCH_SCORE,
                   h.FILE_NAME, h.FILE_PATH, h.FILE_SIZE_KB,
                   h.CATALOGED_BY, h.CATALOG_DATE,
                   STUFF((SELECT ',' + c.MNEMONIC
                          FROM {ct} c WHERE c.FILE_HEADER_ID=h.FILE_HEADER_ID
                          FOR XML PATH('')),1,1,'') AS CURVES
            FROM {ht} h WHERE {where}
            ORDER BY h.FILE_TYPE, h.MATCHED_UWI, h.FILE_NAME
        """
    else:
        sql = f"""
            SELECT h.FILE_HEADER_ID, h.FILE_TYPE, h.MATCHED_UWI, h.WELL_NAME,
                   h.MATCH_METHOD, h.MATCH_SCORE,
                   h.FILE_NAME, h.FILE_PATH, h.FILE_SIZE_KB,
                   h.CATALOGED_BY, h.CATALOG_DATE
            FROM {ht} h WHERE {where}
            ORDER BY h.FILE_TYPE, h.MATCHED_UWI, h.FILE_NAME
        """

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            return pd.DataFrame(result.fetchall(),
                                columns=[c for c in result.keys()])
    except Exception:
        return pd.DataFrame()


def get_header_text(engine, dialect: str, file_header_id: str) -> str:
    """Retrieve raw header text for a single file."""
    ht = _tbl(dialect, "FILE_HEADER")
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT HEADER_TEXT FROM {ht} WHERE FILE_HEADER_ID=:fhid"
            ), {"fhid": file_header_id}).fetchone()
        return row[0] if row else ""
    except Exception:
        return ""


def export_to_pipeline_csv(df: "pd.DataFrame",
                            file_type: str) -> "pd.DataFrame":
    """
    Reformat catalog headers into Data Wrangler pipeline CSV format
    for the relevant PPDM target table.
    LAS/DLIS/LIS → WELL_LOG columns
    SEGY/P190    → SEIS_SET columns
    """
    if file_type in ("LAS","DLIS","LIS"):
        col_map = {
            "MATCHED_UWI":  "UWI",
            "WELL_NAME":    "WELL_LOG_NAME",
            "FILE_NAME":    "SOURCE_FILE",
            "FILE_PATH":    "SOURCE_PATH",
            "CURVES":       "CURVE_LIST",
            "CATALOG_DATE": "LOG_CATALOG_DATE",
        }
    else:
        col_map = {
            "MATCHED_UWI":  "SEIS_SET_ID",
            "WELL_NAME":    "SEIS_SET_NAME",
            "FILE_NAME":    "SOURCE_FILE",
            "FILE_PATH":    "SOURCE_PATH",
            "CATALOG_DATE": "CATALOG_DATE",
        }
    out  = df.rename(columns=col_map)
    keep = [v for v in col_map.values() if v in out.columns]
    return out[keep]


def get_ppdm_well_headers(engine, dialect: str) -> "pd.DataFrame":
    """Pull PPDM well header for comparison."""
    import pandas as pd
    if dialect in ("oracle","snowflake"):
        sql = 'SELECT "UWI","WELL_NAME","OPERATOR","FIELD_NAME" FROM "WELL"'
    else:
        sql = "SELECT uwi AS UWI, well_name AS WELL_NAME, operator_ba_id AS OPERATOR, field_id AS FIELD_NAME FROM dataview.dv_well"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            return pd.DataFrame(result.fetchall(),
                                columns=[c for c in result.keys()])
    except Exception:
        return pd.DataFrame()


def compare_catalog_to_ppdm(catalog_df: "pd.DataFrame",
                              ppdm_df: "pd.DataFrame") -> "pd.DataFrame":
    """Merge catalog vs PPDM and flag differences."""
    import pandas as pd
    if catalog_df.empty or ppdm_df.empty:
        return pd.DataFrame()
    merged = catalog_df.merge(
        ppdm_df, left_on="MATCHED_UWI", right_on="UWI",
        how="left", suffixes=("_CAT","_PPDM")
    )
    merged["STATUS"] = merged.apply(
        lambda r: "NO_PPDM"  if pd.isna(r.get("UWI"))
        else "NAME_DIFFERS"  if str(r.get("WELL_NAME_CAT","")).strip().upper() !=
                                str(r.get("WELL_NAME_PPDM","")).strip().upper()
        else "MATCH", axis=1
    )
    return merged
