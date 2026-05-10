"""
format_library.py
=================
DataView v3 — Universal Well Data Translation Layer.

Provides:
  - Format detection against the registry
  - Inbound adapters: read any format → normalised row dicts
  - Outbound adapters: dv_well rows → any format
  - Bulk loader: fast_executemany into SQL Server
  - Format registration: promote a confirmed ML mapping into the library

Usage:
    from format_library.format_library import FormatLibrary

    lib = FormatLibrary()

    # Detect format
    fmt = lib.detect("training/Kansas/ks_wells_test1.csv")
    print(fmt["display_name"])   # KGS Well Header

    # Load inbound
    rows, errors = lib.read(fmt, "training/Kansas/ks_wells_test1.csv")

    # Bulk insert into dv_well
    lib.load(rows, engine)

    # Export outbound
    lib.write(fmt, rows, "export/ks_wells_out.csv")
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

# ── Registry path ─────────────────────────────────────────────────────
REGISTRY_PATH = Path(__file__).parent / "format_registry.json"
CONFIRMED_PATH = Path(__file__).parent / "confirmed_mappings.json"


class FormatLibrary:
    """Central hub for all format detection, reading, and writing."""

    def __init__(self, registry_path: str | Path = REGISTRY_PATH):
        self.registry_path = Path(registry_path)
        self._registry = self._load_registry()
        self._confirmed = self._load_confirmed()

    # ── Registry ──────────────────────────────────────────────────────

    def _load_registry(self) -> dict:
        return json.loads(self.registry_path.read_text())

    def _load_confirmed(self) -> dict:
        if CONFIRMED_PATH.exists():
            return json.loads(CONFIRMED_PATH.read_text())
        return {}

    def _save_confirmed(self) -> None:
        CONFIRMED_PATH.write_text(json.dumps(self._confirmed, indent=2))

    @property
    def formats(self) -> list[dict]:
        return self._registry["formats"]

    def get_format(self, format_id: str) -> dict | None:
        return next((f for f in self.formats if f["format_id"] == format_id), None)

    def list_formats(self) -> list[dict]:
        """Return summary of all registered formats."""
        return [
            {
                "format_id":    f["format_id"],
                "display_name": f["display_name"],
                "vendor":       f["vendor"],
                "tier":         f["tier"],
                "inbound":      "inbound" in f,
                "outbound":     bool(f.get("outbound", {}).get("format")),
            }
            for f in self.formats
        ]

    # ── Detection ─────────────────────────────────────────────────────

    def detect(self, file_path: str) -> dict | None:
        """
        Identify which registered format matches a file.
        Returns the format dict or None if unknown.
        """
        path = Path(file_path)
        ext  = path.suffix.lower()

        # Read sample
        try:
            sample_text = self._read_sample(path)
        except Exception:
            return None

        for fmt in self.formats:
            det = fmt.get("detection", {})
            det_type = det.get("type", "")

            # Pattern match on filename
            patterns = fmt.get("file_patterns", [])
            if patterns and not any(path.match(p) for p in patterns):
                # Extension doesn't match — but don't hard-exclude, keep checking
                pass

            # Fixed-width with signature regex
            if det_type == "fixed_width" and "signature_regex" in det:
                regex    = det["signature_regex"]
                min_rate = det.get("signature_min_hit_rate", 0.3)
                lines    = [l for l in sample_text.splitlines() if len(l) > 10]
                if not lines:
                    continue
                hits = sum(1 for l in lines[:100] if re.match(regex, l))
                if hits / len(lines[:100]) >= min_rate:
                    return fmt

            # CSV with signature columns
            if det_type == "csv" and "signature_columns" in det:
                try:
                    header = next(csv.reader(io.StringIO(sample_text)))
                    header_set = {c.strip().upper() for c in header}
                    sig_set    = {c.upper() for c in det["signature_columns"]}
                    if sig_set.issubset(header_set):
                        return fmt
                except Exception:
                    pass

            # Binary (shapefile)
            if det_type == "binary" and ext == ".shp":
                if "magic_bytes" in det:
                    with open(path, "rb") as f:
                        header_bytes = f.read(4)
                    if header_bytes.hex() == det["magic_bytes"]:
                        return fmt

            # LAS
            if det_type == "text" and "first_line_match" in det.get("signature",""):
                first = sample_text.splitlines()[0] if sample_text else ""
                if re.match(det.get("signature_regex",""), first):
                    return fmt

        return None

    def _read_sample(self, path: Path, max_bytes: int = 32768) -> str:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
        for enc in ("utf-8", "latin-1"):
            try:
                return raw.decode(enc, errors="replace")
            except Exception:
                pass
        return raw.decode("latin-1", errors="replace")

    # ── Inbound readers ───────────────────────────────────────────────

    def read(
        self,
        fmt: dict,
        file_path: str,
        limit: int | None = None,
    ) -> tuple[list[dict], list[str]]:
        """
        Read a file using its registered inbound adapter.
        Returns (rows, errors) where rows are dicts keyed by dv_well field names.
        """
        reader_type = fmt.get("inbound", {}).get("reader", "csv_robust")

        if reader_type == "fixed_width" and fmt["format_id"] == "rrc_maf016":
            return self._read_rrc_maf016(fmt, file_path, limit)
        elif reader_type in ("csv_robust", "csv_direct"):
            return self._read_csv(fmt, file_path, limit)
        elif reader_type == "las_parser":
            return self._read_las(fmt, file_path, limit)
        elif reader_type == "shapefile":
            return self._read_shapefile(fmt, file_path, limit)
        else:
            return [], [f"No reader implemented for: {reader_type}"]

    # ── CSV reader (handles KGS dirty data) ───────────────────────────

    def _read_csv(
        self,
        fmt: dict,
        file_path: str,
        limit: int | None,
    ) -> tuple[list[dict], list[str]]:
        inbound  = fmt["inbound"]
        field_map = inbound.get("field_map", {})
        status_map = inbound.get("status_map", {})
        date_cols  = inbound.get("date_columns", {})
        str_cols   = set(inbound.get("string_columns", []))
        encoding   = inbound.get("encoding", "utf-8")
        source_val = inbound.get("source_value", "IMPORT")
        uwi_cfg    = inbound.get("uwi_build", {})
        split_cols = inbound.get("split_columns", {})

        rows   = []
        errors = []

        with open(file_path, encoding=encoding, errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for i, raw_row in enumerate(reader):
                if limit and i >= limit:
                    break
                try:
                    row = self._map_csv_row(
                        raw_row, field_map, status_map, date_cols,
                        str_cols, split_cols, uwi_cfg, source_val, fmt
                    )
                    if row:
                        rows.append(row)
                except Exception as e:
                    errors.append(f"Row {i+2}: {e}")

        return rows, errors

    def _map_csv_row(
        self,
        raw: dict,
        field_map: dict,
        status_map: dict,
        date_cols: dict,
        str_cols: set,
        split_cols: dict,
        uwi_cfg: dict,
        source_val: str,
        fmt: dict,
    ) -> dict | None:
        out = {}

        # Map fields
        for src_col, tgt_field in field_map.items():
            if tgt_field is None:
                continue
            val = raw.get(src_col, "").strip()
            if not val or val.lower() in ("unavailable", "unknown", "null", "none"):
                val = None

            # Force string for API/ID fields (prevent scientific notation)
            if src_col in str_cols and val:
                val = str(val).strip()

            # Date parsing
            if src_col in date_cols and val:
                val = _parse_date(val, date_cols[src_col])

            out[tgt_field] = val

        # Split columns (e.g. ELEVATION → value + datum)
        for src_col, split_cfg in split_cols.items():
            raw_val = raw.get(src_col, "").strip()
            if raw_val:
                m = re.match(split_cfg["pattern"], raw_val)
                if m:
                    outputs = split_cfg["outputs"]
                    if len(outputs) > 0:
                        out[outputs[0]] = m.group(1)
                    if len(outputs) > 1:
                        out[outputs[1]] = m.group(2)

        # Status → well_type + well_status
        status_raw = raw.get("STATUS", "").strip()
        if status_raw and status_map:
            mapped = status_map.get(status_raw, {})
            if mapped:
                out["well_type"]   = mapped.get("well_type", "OIL")
                out["well_status"] = mapped.get("well_status", "ACTIVE")
            else:
                out["well_type"]   = "OIL"
                out["well_status"] = "UNKNOWN"

        # UWI construction
        uwi = self._build_uwi(raw, out, uwi_cfg)
        if not uwi:
            return None
        out["uwi"] = uwi

        # Ensure required fields
        out["source"]         = source_val
        out["province_state"] = out.get("province_state") or fmt.get("inbound", {}).get("default_state", "")
        out["country"]        = out.get("country") or "US"
        out["active_ind"]     = "Y" if out.get("well_status") == "ACTIVE" else "N"
        out["row_created_by"] = f"{fmt['format_id'].upper()}_LOADER"
        out["row_changed_by"] = f"{fmt['format_id'].upper()}_LOADER"

        return out

    # ── UWI builder ───────────────────────────────────────────────────

    def _build_uwi(self, raw: dict, out: dict, uwi_cfg: dict) -> str | None:
        method = uwi_cfg.get("method", "from_api")

        if method == "from_api":
            src_col = uwi_cfg.get("source_col", "API_NUMBER")
            api_raw = raw.get(src_col, "").strip()
            if not api_raw:
                return None
            # Strip dashes, pad
            digits = re.sub(r"[^0-9]", "", api_raw)
            if len(digits) < 10:
                return None
            state_fips  = uwi_cfg.get("state_fips", "20")
            county_fips = digits[2:5]
            seq         = digits[5:10]
            sidetrack   = digits[10:12] if len(digits) >= 12 else "00"
            return f"US{state_fips}{county_fips}{seq}{sidetrack}0000"

        if method == "rrc_county_fips":
            # Handled by dedicated RRC reader
            return out.get("uwi")

        return None

    # ── RRC MAF016 reader ─────────────────────────────────────────────

    def _read_rrc_maf016(
        self,
        fmt: dict,
        file_path: str,
        limit: int | None,
    ) -> tuple[list[dict], list[str]]:
        """Dedicated fast reader for MAF016 fixed-width format."""
        inbound    = fmt["inbound"]
        col_pos    = inbound["col_positions"]
        field_map  = inbound["field_map"]
        status_map = inbound["status_map"]
        type_map   = inbound["well_type_map"]
        uwi_cfg    = inbound["uwi_build"]
        source_val = inbound["source_value"]

        # RRC county → FIPS (District 3 + 8)
        RRC_TO_FIPS = {
            "110":"103","120":"105","130":"135","140":"173","210":"227",
            "220":"003","224":"003","230":"301","240":"317","310":"329",
            "320":"371","330":"383","340":"461","350":"445","410":"475",
            "420":"495","430":"501","440":"165","450":"115","460":"033",
            "510":"389","520":"109",
        }
        RRC_COUNTY = {
            "110":"CRANE","120":"CROCKETT","130":"ECTOR","140":"GLASSCOCK",
            "210":"HOWARD","220":"ANDREWS","224":"ANDREWS","230":"LOVING",
            "240":"MARTIN","310":"MIDLAND","320":"PECOS","330":"REAGAN",
            "340":"UPTON","350":"TERRY","410":"WARD","420":"WINKLER",
            "430":"YOAKUM","440":"GAINES","450":"DAWSON","460":"BORDEN",
            "510":"REEVES","520":"CULBERSON",
        }

        rows   = []
        errors = []

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
                    unique   = line[8:14].strip()
                    side     = line[14:15].strip() or "0"
                    fips     = RRC_TO_FIPS.get(county_c, county_c.zfill(3))
                    uwi      = f"US42{fips}{unique}{side.zfill(2)}0000"

                    lease_nm = _clean(line[16:71])
                    operator = _clean(line[71:103])
                    td_s     = "".join(c for c in line[103:109] if c.isdigit())
                    td       = int(td_s) if td_s and int(td_s) > 0 else None
                    field_nm = _clean(line[164:196])
                    type_s   = line[238:240].strip() if len(line) >= 240 else ""

                    dates = re.findall(r"(?:19|20)\d{6}", line[100:])
                    spud  = _parse_date(dates[0], "YYYYMMDD") if dates else None
                    compl = _parse_date(dates[1], "YYYYMMDD") if len(dates) > 1 else None

                    well_type   = type_map.get(type_s, "OIL")
                    well_status = status_map.get(rec_type, "ACTIVE")

                    api_num = f"42-{fips}-{unique}-{side.zfill(2)}"

                    rows.append({
                        "uwi":             uwi,
                        "well_name":       (lease_nm or "UNKNOWN")[:80],
                        "well_type":       well_type,
                        "well_status":     well_status,
                        "province_state":  "TX",
                        "country":         "US",
                        "county":          RRC_COUNTY.get(county_c, county_c)[:50],
                        "operator_name":   operator[:80],
                        "field_name":      field_nm[:80],
                        "final_td":        td,
                        "depth_datum":     "KB",
                        "spud_date":       spud,
                        "completion_date": compl,
                        "api_num":         api_num,
                        "active_ind":      "Y" if well_status == "ACTIVE" else "N",
                        "source":          source_val,
                        "row_created_by":  "MAF016_LOADER",
                        "row_changed_by":  "MAF016_LOADER",
                    })
                except Exception as e:
                    errors.append(f"Line {i+1}: {e}")

        return rows, errors

    # ── LAS reader (stub — full implementation in las_parser.py) ──────

    def _read_las(self, fmt: dict, file_path: str, limit: int | None) -> tuple:
        try:
            from format_library.las_parser import parse_las
            return parse_las(file_path, fmt, limit)
        except ImportError:
            return [], ["las_parser.py not yet implemented"]

    # ── Shapefile reader ──────────────────────────────────────────────

    def _read_shapefile(self, fmt: dict, file_path: str, limit: int | None) -> tuple:
        try:
            import geopandas as gpd
            gdf = gpd.read_file(file_path).to_crs("EPSG:4326")
            if limit:
                gdf = gdf.head(limit)
            rows   = []
            errors = []
            field_map = fmt["inbound"].get("field_map", {})
            for _, r in gdf.iterrows():
                out = {}
                for src, tgt in field_map.items():
                    if tgt and src in r:
                        out[tgt] = r[src]
                out["surface_longitude"] = r.geometry.x
                out["surface_latitude"]  = r.geometry.y
                out["source"]            = fmt["inbound"]["source_value"]
                out["row_created_by"]    = "SHP_LOADER"
                out["row_changed_by"]    = "SHP_LOADER"
                out["active_ind"]        = "Y"
                rows.append(out)
            return rows, errors
        except ImportError:
            return [], ["geopandas not installed — pip install geopandas"]

    # ── Bulk loader ───────────────────────────────────────────────────

    def load(
        self,
        fmt: dict,
        rows: list[dict],
        engine,
        dry_run: bool = False,
        chunk_size: int | None = None,
    ) -> tuple[int, int, int]:
        """
        Bulk insert rows into dataview.dv_well using fast_executemany.
        Returns (inserted, updated, skipped).
        """
        if not rows:
            print("No rows to load")
            return 0, 0, 0

        chunk = chunk_size or fmt.get("inbound", {}).get("chunk_size", 2000)

        # Dedup by UWI
        seen = {}
        for r in rows:
            if r.get("uwi"):
                seen[r["uwi"]] = r
        rows = list(seen.values())
        print(f"Unique UWIs: {len(rows):,}")

        if dry_run:
            print("DRY RUN — first 5 rows:")
            for r in rows[:5]:
                print(f"  {r.get('uwi')} | {r.get('well_name','')[:30]} | "
                      f"{r.get('operator_name','')[:25]} | {r.get('well_status')}")
            return len(rows), 0, 0

        from sqlalchemy import text
        import pandas as pd

        # Get existing UWIs
        with engine.connect() as con:
            existing = set(
                pd.read_sql(text("SELECT uwi FROM dataview.dv_well"), con)["uwi"].tolist()
            )

        new_rows    = [r for r in rows if r["uwi"] not in existing]
        update_rows = [r for r in rows if r["uwi"] in existing]

        print(f"New: {len(new_rows):,}  |  Update: {len(update_rows):,}")

        inserted = updated = skipped = 0

        # ── INSERT new rows ───────────────────────────────────────────
        INSERT_COLS = [
            "uwi", "well_name", "well_type", "well_status", "province_state",
            "country", "county", "operator_name", "field_name", "final_td",
            "depth_datum", "spud_date", "completion_date", "api_num",
            "active_ind", "source", "row_created_by", "row_changed_by",
        ]
        placeholders = ", ".join("?" * len(INSERT_COLS))
        col_list     = ", ".join(INSERT_COLS)
        insert_sql   = (
            f"IF NOT EXISTS (SELECT 1 FROM dataview.dv_well WHERE uwi=?)\n"
            f"INSERT INTO dataview.dv_well ({col_list})\n"
            f"VALUES ({placeholders})"
        )

        if new_rows:
            raw_conn = engine.raw_connection()
            try:
                cursor = raw_conn.cursor()
                cursor.fast_executemany = True
                for i in range(0, len(new_rows), chunk):
                    batch = new_rows[i:i+chunk]
                    params = []
                    for r in batch:
                        # UWI repeated for the IF NOT EXISTS check
                        params.append(tuple(
                            [r["uwi"]] + [r.get(c) for c in INSERT_COLS]
                        ))
                    try:
                        cursor.executemany(insert_sql, params)
                        raw_conn.commit()
                        inserted += len(batch)
                        print(f"  Inserted {inserted:,} / {len(new_rows):,}...")
                    except Exception as e:
                        raw_conn.rollback()
                        skipped += len(batch)
                        print(f"  Chunk error: {e}")
                cursor.close()
            finally:
                raw_conn.close()

        # ── UPDATE existing rows ──────────────────────────────────────
        if update_rows:
            update_sql = """
                UPDATE dataview.dv_well SET
                    well_status      = ?,
                    final_td         = COALESCE(?, final_td),
                    spud_date        = COALESCE(?, spud_date),
                    completion_date  = COALESCE(?, completion_date),
                    api_num          = COALESCE(NULLIF(?,''), api_num),
                    row_changed_by   = ?,
                    row_changed_date = GETDATE()
                WHERE uwi = ?
            """
            raw_conn = engine.raw_connection()
            try:
                cursor = raw_conn.cursor()
                cursor.fast_executemany = True
                for i in range(0, len(update_rows), chunk):
                    batch = update_rows[i:i+chunk]
                    params = [
                        (
                            r.get("well_status"),
                            r.get("final_td"),
                            r.get("spud_date"),
                            r.get("completion_date"),
                            r.get("api_num"),
                            r.get("row_changed_by", "LOADER"),
                            r["uwi"],
                        )
                        for r in batch
                    ]
                    cursor.executemany(update_sql, params)
                    raw_conn.commit()
                    updated += len(batch)
                    print(f"  Updated {updated:,} / {len(update_rows):,}...")
                cursor.close()
            finally:
                raw_conn.close()

        print(f"\nDone — inserted {inserted:,}, updated {updated:,}, skipped {skipped:,}")
        return inserted, updated, skipped

    # ── Outbound writers ──────────────────────────────────────────────

    def write(self, fmt: dict, rows: list[dict], output_path: str) -> int:
        """
        Write rows to output_path in the format's registered outbound format.
        Returns row count written.
        """
        outbound = fmt.get("outbound", {})
        out_fmt  = outbound.get("format", "csv")

        if out_fmt == "csv":
            return self._write_csv(fmt, rows, output_path)
        else:
            raise NotImplementedError(f"Outbound format not yet implemented: {out_fmt}")

    def _write_csv(self, fmt: dict, rows: list[dict], output_path: str) -> int:
        outbound  = fmt.get("outbound", {})
        field_map = outbound.get("field_map", {})
        delimiter = outbound.get("delimiter", ",")

        if not rows:
            return 0

        # Reverse the field map: dv_well field → output column name
        if field_map == "direct":
            out_rows = rows
            headers  = list(rows[0].keys())
        else:
            rev_map = {v: k for k, v in field_map.items() if v}
            headers  = list(field_map.keys())
            out_rows = []
            for r in rows:
                out_rows.append({
                    out_col: r.get(dv_field, "")
                    for out_col, dv_field in field_map.items()
                })

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(out_rows)

        return len(out_rows)

    # ── Format registration ───────────────────────────────────────────

    def register_format(
        self,
        format_id: str,
        display_name: str,
        vendor: str,
        detection: dict,
        field_map: dict,
        file_patterns: list[str] | None = None,
        source_value: str = "IMPORT",
        confirmed_by: str = "user",
    ) -> None:
        """
        Register a new format into the library (promotes a confirmed ML mapping).
        Saves to confirmed_mappings.json and adds to in-memory registry.
        """
        entry = {
            "format_id":    format_id,
            "display_name": display_name,
            "vendor":       vendor,
            "tier":         1,
            "file_patterns": file_patterns or [],
            "detection":    detection,
            "inbound": {
                "reader":       "csv_robust",
                "field_map":    field_map,
                "source_value": source_value,
                "loader":       "bulk_executemany",
                "chunk_size":   2000,
            },
            "outbound": {"format": "csv"},
            "confirmed_by":   confirmed_by,
            "confirmed_date": datetime.now().strftime("%Y-%m-%d"),
        }
        self._confirmed[format_id] = entry
        self._save_confirmed()
        # Add to live registry
        self._registry["formats"].append(entry)
        print(f"Registered format: {display_name} ({format_id})")


# ── Helpers ───────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return " ".join(s.split()) if s else ""


def _parse_date(s: str, fmt: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    if fmt == "YYYYMMDD":
        s = s.replace(" ", "")
        if len(s) == 8 and s.isdigit() and s != "00000000":
            try:
                return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                return None
    if fmt == "DD-Mon-YY":
        for pattern in ("%d-%b-%y", "%d-%b-%Y"):
            try:
                return datetime.strptime(s, pattern).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    lib = FormatLibrary()

    if len(sys.argv) < 2:
        print("Usage: python format_library.py <file_path> [--dry-run] [--limit N]")
        print("\nRegistered formats:")
        for f in lib.list_formats():
            tier = f["tier"]
            io_s = ("→" if f["inbound"] else " ") + ("←" if f["outbound"] else " ")
            print(f"  [{tier}] {io_s}  {f['format_id']:30} {f['display_name']}")
        sys.exit(0)

    file_path = sys.argv[1]
    dry_run   = "--dry-run" in sys.argv
    limit     = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    fmt = lib.detect(file_path)
    if not fmt:
        print(f"Unknown format: {file_path}")
        print("Run column_mapper.py to identify and register this format.")
        sys.exit(1)

    print(f"Detected: {fmt['display_name']} (Tier {fmt['tier']})")
    rows, errors = lib.read(fmt, file_path, limit=limit)
    print(f"Read {len(rows):,} rows, {len(errors)} errors")
    if errors:
        for e in errors[:10]:
            print(f"  {e}")
    if dry_run and rows:
        print("\nFirst 3 rows:")
        for r in rows[:3]:
            print(f"  {r}")
