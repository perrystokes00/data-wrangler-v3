"""
loaders/plugins/kgs.py — KGS (Kansas Geological Survey) wells plugin.

Source: ks_wells.txt (193 MB CSV, 514,713 rows, 43 native columns)
Public download: https://www.kgs.ku.edu/PRS/petro/wells.html

UWI convention: KGS_<KID> (e.g. KGS_1001187266)
Source label:   'KGS'
Native table:   dataview.dv_well_ext_kgs
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

try:
    import h3
except ImportError:
    h3 = None  # parse_rows will skip h3 columns if the library isn't installed

from loaders.core.cleaning import (
    clean_text, parse_float, parse_kgs_date,
)
from loaders.core.plugin_base import (
    ConfidenceScore, ParsedRow, SourcePlugin,
)


# -----------------------------------------------------------------------------
# KGS source column order (matches the published CSV header exactly)
# -----------------------------------------------------------------------------
KGS_COLUMNS = [
    "KID", "API_NUMBER", "API_NUM_NODASH", "LEASE", "WELL", "FIELD",
    "LATITUDE", "LONGITUDE", "LONG_LAT_SOURCE",
    "TOWNSHIP", "TWN_DIR", "RANGE", "RANGE_DIR", "SECTION", "SPOT",
    "FEET_NORTH", "FEET_EAST", "FOOT_REF",
    "ORIG_OPERATOR", "CURR_OPERATOR",
    "ELEVATION", "ELEV_REF", "SURFACE_ELEVATION_LIDAR",
    "DEPTH", "FORMATION_AT_TOTAL_DEPTH", "PRODUCE_FORM",
    "IP_OIL", "IP_GAS", "IP_WATER",
    "PERMIT", "SPUD", "COMPLETION", "PLUGGING", "MODIFIED",
    "OIL_KID", "OIL_DOR_ID", "GAS_KID", "GAS_DOR_ID", "KCC_PERMIT",
    "STATUS", "STATUS2", "COMMENTS", "LEASE_WELL_NAME",
]

# Reserved word renames for dv_well_ext_kgs DDL
# (RANGE → RANGE_, SECTION → SECTION_)
RESERVED_RENAMES = {"RANGE": "RANGE_", "SECTION": "SECTION_"}


def _compute_h3(lat: float | None, lon: float | None) -> dict:
    """
    Compute the 5 h3 values that dv_well expects for a given coordinate.

    Returns a dict with keys: h3_r4, h3_r5, h3_r6, h3_r7, h3_coord_hash.
    All values are None if lat or lon is None, or if the h3 library isn't
    installed. The runner writes None as a NULL in BCP — and since we
    relaxed the NOT NULL constraint on these columns (2026-05-28),
    null h3 for null coords is acceptable.

    h3_coord_hash format: SHA-256 of f"{lat}|{lon}" using Python's
    default float repr (no padding). Returned as an UPPERCASE hex string
    of length 64 — BCP -c mode interprets this as the BINARY(32) value.
    Empirically reverse-engineered from existing dv_well rows; must
    match that convention exactly so federation density views and any
    coord-based dedup join correctly across sources.

    h3_r4..r7: H3 cell identifiers as 15-char hex strings.
    """
    if lat is None or lon is None or h3 is None:
        return {
            "h3_r4": None, "h3_r5": None, "h3_r6": None, "h3_r7": None,
            "h3_coord_hash": None,
        }
    return {
        "h3_r4": h3.latlng_to_cell(lat, lon, 4),
        "h3_r5": h3.latlng_to_cell(lat, lon, 5),
        "h3_r6": h3.latlng_to_cell(lat, lon, 6),
        "h3_r7": h3.latlng_to_cell(lat, lon, 7),
        "h3_coord_hash": hashlib.sha256(
            f"{lat}|{lon}".encode("utf-8")
        ).hexdigest().upper(),
    }



class KGSPlugin(SourcePlugin):
    name = "KGS"
    description = "Kansas Geological Survey wells (kgs.ku.edu public CSV)"
    native_table = "dataview.dv_well_ext_kgs"
    source_label = "KGS"

    # ------------------------------------------------------------------
    # Detection: header signature match
    # ------------------------------------------------------------------
    def detect(self, path: Path) -> ConfidenceScore:
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as f:
                first = f.readline()
        except OSError as e:
            return ConfidenceScore(0, f"could not read file: {e}")

        # Normalize: uppercase, strip quotes, replace separators with commas.
        # This makes the test tolerant of:
        #   - quoted vs unquoted column names ("KID" vs KID)
        #   - UTF-8 BOM (handled by utf-8-sig encoding)
        #   - comma, pipe, tab, or semicolon as the field separator
        norm = first.upper()
        for ch in ('"', "'"):
            norm = norm.replace(ch, "")
        for ch in ("|", "\t", ";"):
            norm = norm.replace(ch, ",")
        tokens = {t.strip() for t in norm.split(",")}

        # Signature columns that together strongly indicate KGS
        signature_cols = {"KID", "API_NUM_NODASH", "ORIG_OPERATOR", "PRODUCE_FORM"}
        hits = signature_cols & tokens

        if len(hits) == len(signature_cols):
            return ConfidenceScore(
                95,
                f"Header contains all {len(signature_cols)} KGS-distinctive columns"
            )
        elif len(hits) >= 2:
            return ConfidenceScore(
                50,
                f"Header contains {len(hits)} of {len(signature_cols)} KGS columns "
                "(partial match — please confirm)"
            )
        return ConfidenceScore(0, "Header does not match KGS signature")

    # ------------------------------------------------------------------
    # Native column order — must match dv_well_ext_kgs DDL
    # ------------------------------------------------------------------
    def native_column_order(self) -> list[str]:
        cols = ["uwi"]
        cols.extend(RESERVED_RENAMES.get(c, c) for c in KGS_COLUMNS)
        cols.append("loaded_date")
        return cols

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def parse_rows(self, path: Path) -> Iterator[ParsedRow]:
        load_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Raise the CSV field-size limit — some KGS COMMENTS rows are long
        csv.field_size_limit(10_000_000)

        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)

            # Build column index map (handles minor header reordering)
            col_idx = {name: i for i, name in enumerate(header)}

            def C(row: list[str], name: str) -> str:
                i = col_idx.get(name)
                if i is None or i >= len(row):
                    return ""
                return row[i]

            for row in reader:
                kid = (C(row, "KID") or "").strip()
                if not kid:
                    # Skip rows without a KID — they have no PK
                    continue

                uwi = f"KGS_{kid}"

                # ───── Cleaned values ─────
                api_number   = clean_text(C(row, "API_NUMBER"), 40)
                lease        = clean_text(C(row, "LEASE"))
                well         = clean_text(C(row, "WELL"))
                field_name   = clean_text(C(row, "FIELD"), 255)
                lease_well   = clean_text(C(row, "LEASE_WELL_NAME"), 255)
                curr_op      = clean_text(C(row, "CURR_OPERATOR"), 255)
                status       = clean_text(C(row, "STATUS"), 40)
                formation_td = clean_text(C(row, "FORMATION_AT_TOTAL_DEPTH"), 255)
                produce_form = clean_text(C(row, "PRODUCE_FORM"), 255)
                ll_source    = clean_text(C(row, "LONG_LAT_SOURCE"), 40)
                permit       = clean_text(C(row, "PERMIT"), 40)

                lat        = parse_float(C(row, "LATITUDE"))
                lon        = parse_float(C(row, "LONGITUDE"))
                depth      = parse_float(C(row, "DEPTH"))
                elev       = parse_float(C(row, "ELEVATION"))
                elev_lidar = parse_float(C(row, "SURFACE_ELEVATION_LIDAR"))

                spud_date = parse_kgs_date(C(row, "SPUD"))
                comp_date = parse_kgs_date(C(row, "COMPLETION"))
                plug_date = parse_kgs_date(C(row, "PLUGGING"))

                # ───── Native columns (for dv_well_ext_kgs) ─────
                native_columns = {"uwi": uwi}
                for kgs_col in KGS_COLUMNS:
                    raw = C(row, kgs_col)
                    cleaned = None
                    if raw is not None:
                        cleaned = re.sub(r"[\r\n\t]+", " ", raw)
                        cleaned = cleaned.replace("|", " ").strip()
                        cleaned = cleaned or None
                    target_col = RESERVED_RENAMES.get(kgs_col, kgs_col)
                    native_columns[target_col] = cleaned
                native_columns["loaded_date"] = load_ts

                # ───── Common (dv_well) columns ─────
                well_name_value = lease_well or (
                    f"{lease} {well}".strip() if (lease or well) else None
                )
                if well_name_value:
                    well_name_value = clean_text(well_name_value, 255)

                # ───── H3 cells + coord hash (computed inline) ─────
                # 2026-05-28: previously deferred to backfill_h3_bcp.py, but
                # the schema's NOT NULL constraint (since relaxed) plus the
                # extra orchestration step made that flow brittle. Computing
                # during parse keeps the load single-step and means a fresh
                # load is immediately ready for the map's density views.
                h3_vals = _compute_h3(lat, lon)

                well_columns = {
                    "uwi":                  uwi,
                    "well_name":            well_name_value,
                    "well_num":             clean_text(well, 40),
                    "well_status":          status,
                    "country":              "USA",
                    "province_state":       "KS",
                    "legal_survey_type":    "PLSS",
                    "surface_latitude":     lat,
                    "surface_longitude":    lon,
                    "ground_elevation":     elev_lidar or elev,
                    "spud_date":            spud_date,
                    "completion_date":      comp_date,
                    "final_td":             depth,
                    "epsg_code":            4326,
                    "api_num":              api_number,
                    "lease_name":           clean_text(lease, 255),
                    "onshore_offshore_ind": "ONSHORE",
                    "active_ind":           "Y",
                    "row_created_by":       "KGS_LOADER",
                    "row_created_date":     load_ts,
                    "source":               self.source_label,
                    "abandonment_date":     plug_date,
                    "elevation_ouom":       "FT",
                    "formation_at_td":      formation_td,
                    "long_lat_source":      ll_source,
                    "permit_number":        permit,
                    "producing_formation":  produce_form,
                    "operator_name":        curr_op,
                    "field_name":           field_name,
                    "h3_r4":                h3_vals["h3_r4"],
                    "h3_r5":                h3_vals["h3_r5"],
                    "h3_r6":                h3_vals["h3_r6"],
                    "h3_r7":                h3_vals["h3_r7"],
                    "h3_coord_hash":        h3_vals["h3_coord_hash"],
                }

                # ───── Identifier crosswalk ─────
                identifiers = [
                    ("UWI", uwi, True),
                    ("KID", kid, False),
                ]
                if api_number:
                    identifiers.append(("API", api_number, False))

                yield ParsedRow(
                    uwi=uwi,
                    native_columns=native_columns,
                    well_columns=well_columns,
                    identifiers=identifiers,
                )
