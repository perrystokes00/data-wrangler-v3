"""
generate_dataview_schema.py
===========================
Generates the DataView schema registry files consumed by the v2 pipeline:

  1. dataview_schema_domain.json   — column-grained catalog consumed by schema.py
  2. dataview_fk_catalog.json      — FK / PK / column catalog consumed by fk_catalog.py

Two modes — use ONE:

  Live DB (preferred):
    python generate_dataview_schema.py --conn "mssql+pyodbc://./SQLEXPRESS/DataView?driver=ODBC+Driver+17+for+SQL+Server&Trusted_Connection=yes"

  Offline DDL:
    python generate_dataview_schema.py --ddl dataview_ddl.sql

Common options:
    --out-dir schema_registry     Output directory (default: schema_registry)
    --schemas dataview             Schema(s) to include (default: dataview)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

DOMAIN_ROOT_KEY = "dataview_schema_domain"

# Table-name prefix → category (for domain JSON grouping in schema.py UI)
_CATEGORY_MAP = {
    "dv_well":           "WELL",
    "dv_prod":           "PROD",
    "dv_seis":           "SEIS",
    "dv_strat":          "WELL",
    "dv_r_":             "REF",
    "dv_spatial":        "SPATIAL",
    "dv_basin":          "SPATIAL",
    "dv_country":        "SPATIAL",
    "dv_county":         "SPATIAL",
    "dv_province_state": "SPATIAL",
    "dv_ocs_block":      "SPATIAL",
    "dv_plss_township":  "SPATIAL",
    "dv_business":       "BA",
    "dv_field":          "ENTITY",
    "dv_load_batch":     "ADMIN",
    "dv_data_quality":   "ADMIN",
    "dv_column_map":     "ADMIN",
    "dv_source":         "ADMIN",
    "dv_stg_":           "STAGING",
    "dv_global_file":    "CATALOG",
    "dv_wl_file":        "CATALOG",
    "dv_seis_file":      "CATALOG",
    "document_location": "CATALOG",
    "state_polygon":     "SPATIAL",
}


def _classify_category(table_name: str) -> str:
    """Return a category string for the domain JSON, matching longest prefix."""
    best_cat, best_len = "OTHER", 0
    for prefix, cat in _CATEGORY_MAP.items():
        if table_name.startswith(prefix) and len(prefix) > best_len:
            best_cat, best_len = cat, len(prefix)
    return best_cat


def _classify_kind(table_name: str) -> str:
    """Return 'reference' or 'entity' for the FK catalog."""
    return "reference" if table_name.startswith("dv_r_") else "entity"


# ═══════════════════════════════════════════════════════════════════════
# INTERMEDIATE MODEL
# ═══════════════════════════════════════════════════════════════════════

class ColumnInfo:
    __slots__ = ("name", "data_type", "nullable", "identity", "computed",
                 "base_type", "max_length")

    def __init__(self, name: str, data_type: str, nullable: bool,
                 identity: bool = False, computed: bool = False):
        self.name = name
        self.data_type = data_type          # e.g. "nvarchar(40)", "numeric(15,10)"
        self.nullable = nullable
        self.identity = identity
        self.computed = computed
        # derived for FK catalog
        bt, ml = self._parse_type(data_type)
        self.base_type = bt                 # e.g. "NVARCHAR"
        self.max_length = ml                # char length for strings, else 0

    @staticmethod
    def _parse_type(dt: str) -> tuple[str, int]:
        m = re.match(r"(\w+)(?:\(([^)]*)\))?", dt)
        if not m:
            return dt.upper(), 0
        base = m.group(1).upper()
        args = m.group(2)
        if base in ("NVARCHAR", "VARCHAR", "NCHAR", "CHAR") and args:
            if args.strip().upper() == "MAX":
                return base, -1
            return base, int(args.strip())
        return base, 0


class TableInfo:
    def __init__(self, schema: str, name: str):
        self.schema = schema
        self.name = name
        self.columns: OrderedDict[str, ColumnInfo] = OrderedDict()
        self.pk_cols: list[str] = []
        self.checks: list[tuple[str, str]] = []   # (constraint_name, predicate_text)


class FKInfo:
    def __init__(self, child_schema: str, child_table: str,
                 constraint_name: str,
                 child_cols: list[str],
                 parent_schema: str, parent_table: str,
                 parent_cols: list[str]):
        self.child_schema = child_schema
        self.child_table = child_table
        self.constraint_name = constraint_name
        self.child_cols = child_cols
        self.parent_schema = parent_schema
        self.parent_table = parent_table
        self.parent_cols = parent_cols

    @property
    def is_composite(self) -> bool:
        return len(self.child_cols) > 1


# ═══════════════════════════════════════════════════════════════════════
# DDL PARSER
# ═══════════════════════════════════════════════════════════════════════

_RE_CREATE_TABLE = re.compile(
    r"^CREATE TABLE \[(\w+)\]\.\[(\w+)\]\(", re.MULTILINE
)
_RE_COLUMN = re.compile(
    r"^\t\[(\w+)\]\s+(.+)$"
)
_RE_PK_START = re.compile(
    r"^\s*CONSTRAINT\s+\[\w+\]\s+PRIMARY KEY"
)
_RE_PK_COL = re.compile(
    r"^\t\[(\w+)\]\s+(?:ASC|DESC)"
)
_RE_FK = re.compile(
    r"^ALTER TABLE \[(\w+)\]\.\[(\w+)\]\s+WITH (?:NO)?CHECK ADD\s+"
    r"(?:CONSTRAINT \[(\w+)\]\s+)?FOREIGN KEY\(([^)]+)\)\s*$",
    re.MULTILINE
)
_RE_REFERENCES = re.compile(
    r"^REFERENCES \[(\w+)\]\.\[(\w+)\]\s+\(([^)]+)\)", re.MULTILINE
)
_RE_CHECK = re.compile(
    r"^ALTER TABLE \[(\w+)\]\.\[(\w+)\]\s+WITH (?:NO)?CHECK ADD\s+"
    r"CONSTRAINT \[(\w+)\]\s+CHECK\s+\((.+)\)\s*$",
    re.MULTILINE
)


def _parse_col_rest(rest: str) -> Optional[ColumnInfo]:
    """Parse the portion after [col_name] in a CREATE TABLE column line."""
    rest = rest.rstrip(",").strip()

    # Computed column: [col]  AS (expression)
    if rest.startswith("AS ") or rest.startswith("AS\t"):
        return ColumnInfo(name="", data_type="computed", nullable=True, computed=True)

    # Normal: [type](args) [IDENTITY(s,i)] [NOT] NULL
    m = re.match(r"\[(\w+)\](?:\(([^)]*)\))?\s*(.*)", rest)
    if not m:
        return None

    base_type = m.group(1).lower()
    type_args = m.group(2)
    remainder = m.group(3).strip()

    # Build data_type string
    if type_args:
        clean_args = re.sub(r"\s+", "", type_args)  # remove spaces: "15, 10" → "15,10"
        data_type = f"{base_type}({clean_args})"
    else:
        data_type = base_type

    identity = "IDENTITY" in remainder.upper()
    nullable = "NOT NULL" not in remainder.upper()

    return ColumnInfo(name="", data_type=data_type, nullable=nullable, identity=identity)


def _extract_bracketed_cols(s: str) -> list[str]:
    """Extract column names from '[col1],[col2]' style strings."""
    return [m.group(1) for m in re.finditer(r"\[(\w+)\]", s)]


def _read_ddl(path: Path) -> str:
    """Read DDL file, handling UTF-16 and UTF-8 with BOM."""
    raw = path.read_bytes()
    # UTF-16 LE BOM
    if raw[:2] == b"\xff\xfe":
        text = raw.decode("utf-16-le")
    # UTF-16 BE BOM
    elif raw[:2] == b"\xfe\xff":
        text = raw.decode("utf-16-be")
    # UTF-8 BOM
    elif raw[:3] == b"\xef\xbb\xbf":
        text = raw[3:].decode("utf-8")
    else:
        text = raw.decode("utf-8")
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip BOM character if still present
    text = text.lstrip("\ufeff")
    return text


def parse_ddl(path: Path, include_schemas: set[str] | None = None
              ) -> tuple[dict[str, TableInfo], list[FKInfo]]:
    """
    Parse an SSMS-generated DDL script.

    Returns:
        tables: dict of "schema.table_name" → TableInfo
        fk_list: list of FKInfo
    """
    text = _read_ddl(path)
    include = include_schemas or {"dataview"}

    tables: dict[str, TableInfo] = {}
    fk_list: list[FKInfo] = []

    # Split into GO-delimited batches
    batches = re.split(r"^GO\s*$", text, flags=re.MULTILINE)

    for batch in batches:
        batch = batch.strip()
        if not batch:
            continue

        # ── CREATE TABLE ────────────────────────────────────────
        ct_match = _RE_CREATE_TABLE.search(batch)
        if ct_match:
            schema, table = ct_match.group(1).lower(), ct_match.group(2).lower()
            if schema not in include:
                continue

            key = f"{schema}.{table}"
            tinfo = TableInfo(schema, table)

            lines = batch.split("\n")
            in_pk = False
            for line in lines:
                # PK block start
                if _RE_PK_START.match(line):
                    in_pk = True
                    continue

                if in_pk:
                    pk_m = _RE_PK_COL.match(line)
                    if pk_m:
                        tinfo.pk_cols.append(pk_m.group(1).lower())
                    # End of PK block
                    if line.strip().startswith(")"):
                        in_pk = False
                    continue

                # Column line
                col_m = _RE_COLUMN.match(line)
                if col_m:
                    col_name = col_m.group(1).lower()
                    rest = col_m.group(2)
                    cinfo = _parse_col_rest(rest)
                    if cinfo:
                        cinfo.name = col_name
                        tinfo.columns[col_name] = cinfo

            tables[key] = tinfo
            continue

        # ── FOREIGN KEY ─────────────────────────────────────────
        fk_match = _RE_FK.search(batch)
        if fk_match:
            child_schema = fk_match.group(1).lower()
            child_table = fk_match.group(2).lower()
            if child_schema not in include:
                continue
            constraint_name = fk_match.group(3) or ""
            child_cols = [c.lower() for c in _extract_bracketed_cols(fk_match.group(4))]

            ref_match = _RE_REFERENCES.search(batch)
            if ref_match:
                parent_schema = ref_match.group(1).lower()
                parent_table = ref_match.group(2).lower()
                parent_cols = [c.lower() for c in _extract_bracketed_cols(ref_match.group(3))]

                # Generate a name for unnamed FKs
                if not constraint_name:
                    constraint_name = f"fk_{child_table}_{'_'.join(child_cols)}"

                fk_list.append(FKInfo(
                    child_schema=child_schema,
                    child_table=child_table,
                    constraint_name=constraint_name,
                    child_cols=child_cols,
                    parent_schema=parent_schema,
                    parent_table=parent_table,
                    parent_cols=parent_cols,
                ))
            continue

        # ── CHECK CONSTRAINT ────────────────────────────────────
        ck_match = _RE_CHECK.search(batch)
        if ck_match:
            ck_schema = ck_match.group(1).lower()
            ck_table = ck_match.group(2).lower()
            if ck_schema not in include:
                continue
            ck_name = ck_match.group(3)
            ck_pred = ck_match.group(4)
            key = f"{ck_schema}.{ck_table}"
            if key in tables:
                tables[key].checks.append((ck_name, ck_pred))
            continue

    return tables, fk_list


# ═══════════════════════════════════════════════════════════════════════
# DB INTROSPECTOR  — live SQL Server via sqlalchemy
# ═══════════════════════════════════════════════════════════════════════

def parse_db(conn_str: str, include_schemas: set[str] | None = None
             ) -> tuple[dict[str, TableInfo], list[FKInfo]]:
    """
    Introspect a live SQL Server database via sys.* catalog views.
    Returns the same (tables, fk_list) as parse_ddl().

    Requires: sqlalchemy, pyodbc
    """
    from sqlalchemy import create_engine, text

    include = include_schemas or {"dataview"}
    schema_placeholders = ", ".join(f"'{s}'" for s in include)

    engine = create_engine(conn_str)
    tables: dict[str, TableInfo] = {}
    fk_list: list[FKInfo] = []

    with engine.connect() as con:

        # ── 1. Table list ───────────────────────────────────────
        rows = con.execute(text(f"""
            SELECT s.name AS sch, t.name AS tbl
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name IN ({schema_placeholders})
            ORDER BY s.name, t.name
        """)).fetchall()

        for sch, tbl in rows:
            key = f"{sch.lower()}.{tbl.lower()}"
            tables[key] = TableInfo(sch.lower(), tbl.lower())

        # ── 2. Columns ─────────────────────────────────────────
        col_rows = con.execute(text(f"""
            SELECT
                s.name       AS sch,
                t.name       AS tbl,
                c.name       AS col,
                tp.name      AS base_type,
                c.max_length,
                c.precision,
                c.scale,
                c.is_nullable,
                c.is_identity,
                c.is_computed
            FROM sys.columns c
            JOIN sys.types   tp ON tp.user_type_id = c.user_type_id
            JOIN sys.tables  t  ON t.object_id = c.object_id
            JOIN sys.schemas s  ON s.schema_id = t.schema_id
            WHERE s.name IN ({schema_placeholders})
            ORDER BY s.name, t.name, c.column_id
        """)).fetchall()

        for row in col_rows:
            sch, tbl, col = row[0].lower(), row[1].lower(), row[2].lower()
            base_type, max_len, prec, scale = row[3].lower(), row[4], row[5], row[6]
            is_nullable, is_identity, is_computed = bool(row[7]), bool(row[8]), bool(row[9])

            # Format data_type string to match schema.py convention
            if base_type in ("nvarchar", "nchar"):
                if max_len == -1:
                    dt = f"{base_type}(max)"
                else:
                    dt = f"{base_type}({max_len // 2})"
            elif base_type in ("varchar", "char", "varbinary"):
                if max_len == -1:
                    dt = f"{base_type}(max)"
                else:
                    dt = f"{base_type}({max_len})"
            elif base_type in ("decimal", "numeric"):
                dt = f"{base_type}({prec},{scale})"
            elif base_type == "datetime2":
                dt = f"datetime2({scale})"
            else:
                dt = base_type

            key = f"{sch}.{tbl}"
            if key in tables:
                tables[key].columns[col] = ColumnInfo(
                    name=col, data_type=dt, nullable=is_nullable,
                    identity=is_identity, computed=is_computed
                )

        # ── 3. Primary keys ────────────────────────────────────
        pk_rows = con.execute(text(f"""
            SELECT
                s.name  AS sch,
                t.name  AS tbl,
                c.name  AS col
            FROM sys.indexes i
            JOIN sys.index_columns ic ON ic.object_id = i.object_id
                                     AND ic.index_id  = i.index_id
            JOIN sys.columns c  ON c.object_id = i.object_id
                               AND c.column_id = ic.column_id
            JOIN sys.tables  t  ON t.object_id = i.object_id
            JOIN sys.schemas s  ON s.schema_id = t.schema_id
            WHERE i.is_primary_key = 1
              AND s.name IN ({schema_placeholders})
            ORDER BY s.name, t.name, ic.key_ordinal
        """)).fetchall()

        for sch, tbl, col in pk_rows:
            key = f"{sch.lower()}.{tbl.lower()}"
            if key in tables:
                tables[key].pk_cols.append(col.lower())

        # ── 4. Foreign keys (handles composites) ───────────────
        fk_rows = con.execute(text(f"""
            SELECT
                cs.name  AS child_schema,
                ct.name  AS child_table,
                fk.name  AS constraint_name,
                cc.name  AS child_col,
                ps.name  AS parent_schema,
                pt.name  AS parent_table,
                pc.name  AS parent_col,
                fkc.constraint_column_id AS ordinal
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
            JOIN sys.tables  ct ON ct.object_id = fk.parent_object_id
            JOIN sys.schemas cs ON cs.schema_id = ct.schema_id
            JOIN sys.columns cc ON cc.object_id = fk.parent_object_id
                               AND cc.column_id = fkc.parent_column_id
            JOIN sys.tables  pt ON pt.object_id = fk.referenced_object_id
            JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
            JOIN sys.columns pc ON pc.object_id = fk.referenced_object_id
                               AND pc.column_id = fkc.referenced_column_id
            WHERE cs.name IN ({schema_placeholders})
            ORDER BY cs.name, ct.name, fk.name, fkc.constraint_column_id
        """)).fetchall()

        # Group by constraint_name to assemble composite FKs
        from collections import defaultdict as _dd
        fk_groups: dict[str, list] = _dd(list)
        for row in fk_rows:
            fk_groups[row[2]].append(row)  # keyed by constraint_name

        for cname, group in fk_groups.items():
            group.sort(key=lambda r: r[7])  # order by ordinal
            first = group[0]
            child_schema = first[0].lower()
            if child_schema not in include:
                continue
            fk_list.append(FKInfo(
                child_schema=child_schema,
                child_table=first[1].lower(),
                constraint_name=cname,
                child_cols=[r[3].lower() for r in group],
                parent_schema=first[4].lower(),
                parent_table=first[5].lower(),
                parent_cols=[r[6].lower() for r in group],
            ))

        # ── 5. CHECK constraints ───────────────────────────────
        ck_rows = con.execute(text(f"""
            SELECT
                s.name  AS sch,
                t.name  AS tbl,
                cc.name AS ck_name,
                cc.definition AS ck_def
            FROM sys.check_constraints cc
            JOIN sys.tables  t ON t.object_id = cc.parent_object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name IN ({schema_placeholders})
            ORDER BY s.name, t.name, cc.name
        """)).fetchall()

        for sch, tbl, ck_name, ck_def in ck_rows:
            key = f"{sch.lower()}.{tbl.lower()}"
            if key in tables:
                tables[key].checks.append((ck_name, ck_def))

    engine.dispose()
    return tables, fk_list


# ═══════════════════════════════════════════════════════════════════════
# FK INDEX  — build per-table, per-column single-FK lookup
# ═══════════════════════════════════════════════════════════════════════

def _build_single_fk_index(fk_list: list[FKInfo]) -> dict[str, dict[str, FKInfo]]:
    """
    Build {schema.child_table: {child_col: FKInfo}} for single-column FKs only.
    Composite FKs are excluded (they belong in the FK catalog).
    """
    idx: dict[str, dict[str, FKInfo]] = {}
    for fk in fk_list:
        if fk.is_composite:
            continue
        key = f"{fk.child_schema}.{fk.child_table}"
        col = fk.child_cols[0]
        idx.setdefault(key, {})[col] = fk
    return idx


# ═══════════════════════════════════════════════════════════════════════
# EMITTERS
# ═══════════════════════════════════════════════════════════════════════

def _build_check_string(checks: list[tuple[str, str]]) -> str:
    """
    Build the pipe-delimited check constraint string expected by schema.py.
    Format: "CK_NAME: (predicate) | CK_NAME2: (predicate)"
    """
    if not checks:
        return ""
    return " | ".join(f"{name}: ({pred})" for name, pred in checks)


def emit_domain_json(tables: dict[str, TableInfo],
                     fk_list: list[FKInfo]) -> dict:
    """
    Produce the column-grained domain JSON consumed by schema.py's
    load_schema_from_dict().

    Structure:
      { "dataview_schema_domain": [ {one record per column}, ... ] }

    Single-column FKs are inlined on the column record.
    Composite FKs are NOT represented here (carried by FK catalog).
    """
    single_fk_idx = _build_single_fk_index(fk_list)
    records = []

    for key in sorted(tables.keys()):
        tinfo = tables[key]
        category = _classify_category(tinfo.name)
        sub_category = tinfo.name
        check_str = _build_check_string(tinfo.checks)

        for col_name, cinfo in tinfo.columns.items():
            is_pk = col_name in tinfo.pk_cols

            # Single-col FK lookup
            fk = single_fk_idx.get(key, {}).get(col_name)

            record = {
                "model":            "DataView",
                "category":         category,
                "sub_category":     sub_category,
                "table_schema":     tinfo.schema,
                "table_name":       tinfo.name,
                "column_name":      col_name,
                "data_type":        cinfo.data_type,
                "not_null":         "NO" if cinfo.nullable else "YES",
                "is_primary_key":   "YES" if is_pk else "NO",
                "is_foreign_key":   "YES" if fk else "NO",
                "fk_table_schema":  fk.parent_schema if fk else None,
                "fk_table_name":    fk.parent_table if fk else None,
                "fk_column_name":   fk.parent_cols[0] if fk else None,
                "check_constraints": check_str,
            }
            records.append(record)

    return {DOMAIN_ROOT_KEY: records}


def emit_fk_catalog_json(tables: dict[str, TableInfo],
                         fk_list: list[FKInfo]) -> dict:
    """
    Produce the FK catalog JSON consumed by fk_catalog.py's FKCatalog class.

    Structure:
      {
        "dialect": "sqlserver",
        "schema": "dataview",
        "built_at": "...",
        "fk_constraints": { "TABLE_NAME": [ {...}, ... ] },
        "table_pk":       { "TABLE_NAME": ["COL", ...] },
        "table_cols":     { "TABLE_NAME": {"COL": {type, nullable, max_length}} },
        "table_kind":     { "TABLE_NAME": "entity" | "reference" }
      }

    All table/column names are UPPER to match PPDM catalog convention.
    Includes ALL FKs (single and composite).
    """
    fk_constraints: dict[str, list[dict]] = {}
    table_pk: dict[str, list[str]] = {}
    table_cols: dict[str, dict[str, dict]] = {}
    table_kind: dict[str, str] = {}

    # Build table-level data
    for key, tinfo in sorted(tables.items()):
        tname_upper = tinfo.name.upper()
        table_pk[tname_upper] = [c.upper() for c in tinfo.pk_cols]
        table_kind[tname_upper] = _classify_kind(tinfo.name)

        cols_dict: dict[str, dict] = {}
        for col_name, cinfo in tinfo.columns.items():
            cols_dict[col_name.upper()] = {
                "type": cinfo.base_type,
                "nullable": cinfo.nullable,
                "max_length": cinfo.max_length,
            }
        table_cols[tname_upper] = cols_dict

    # Build FK constraints (ALL — single and composite)
    for fk in fk_list:
        tname_upper = fk.child_table.upper()
        tkey = f"{fk.child_schema}.{fk.child_table}"

        # Determine nullable: true if ANY child column is nullable
        tinfo = tables.get(tkey)
        fk_nullable = True
        if tinfo:
            fk_nullable = any(
                tinfo.columns.get(c, ColumnInfo("", "", True)).nullable
                for c in fk.child_cols
            )

        entry = {
            "constraint_name": fk.constraint_name.upper(),
            "child_cols":  [c.upper() for c in fk.child_cols],
            "parent_table": fk.parent_table.upper(),
            "parent_cols": [c.upper() for c in fk.parent_cols],
            "nullable": fk_nullable,
        }
        fk_constraints.setdefault(tname_upper, []).append(entry)

    # Determine schema from first table
    first_schema = "dataview"
    if tables:
        first_schema = next(iter(tables.values())).schema

    return {
        "dialect": "sqlserver",
        "schema": first_schema,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "fk_constraints": fk_constraints,
        "table_pk": table_pk,
        "table_cols": table_cols,
        "table_kind": table_kind,
    }


# ═══════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def validate_domain(data: dict) -> list[str]:
    """Structural validation of domain JSON against schema.py contract."""
    errors = []

    records = data.get(DOMAIN_ROOT_KEY)
    if records is None:
        errors.append(f"Missing root key '{DOMAIN_ROOT_KEY}'")
        return errors
    if not isinstance(records, list):
        errors.append(f"Root key must be a list, got {type(records).__name__}")
        return errors

    required = {"table_name", "column_name", "data_type",
                "not_null", "is_primary_key", "is_foreign_key"}
    yes_no_fields = {"not_null", "is_primary_key", "is_foreign_key"}

    for i, rec in enumerate(records[:5]):  # spot-check first 5
        missing = required - set(rec.keys())
        if missing:
            errors.append(f"Record {i}: missing fields {missing}")
        for f in yes_no_fields:
            val = rec.get(f, "")
            if val not in ("YES", "NO"):
                errors.append(f"Record {i}: {f}='{val}' not YES/NO")

    # Check FK consistency: is_foreign_key=YES must have fk_table_name
    fk_records = [r for r in records if r.get("is_foreign_key") == "YES"]
    for r in fk_records[:3]:
        if not r.get("fk_table_name"):
            errors.append(f"FK column {r['table_name']}.{r['column_name']} "
                         f"has is_foreign_key=YES but no fk_table_name")

    return errors


def validate_fk_catalog(data: dict) -> list[str]:
    """Structural validation of FK catalog JSON against fk_catalog.py contract."""
    errors = []
    expected_keys = {"dialect", "schema", "built_at",
                     "fk_constraints", "table_pk", "table_cols", "table_kind"}
    missing = expected_keys - set(data.keys())
    if missing:
        errors.append(f"Missing top-level keys: {missing}")
        return errors

    # Spot-check FK constraint entries
    for tbl, fks in list(data["fk_constraints"].items())[:3]:
        for fk in fks:
            for field in ("constraint_name", "child_cols", "parent_table",
                         "parent_cols", "nullable"):
                if field not in fk:
                    errors.append(f"FK on {tbl}: missing '{field}'")

    # Check all table names are UPPER
    for section in ("table_pk", "table_cols", "table_kind"):
        for tbl in list(data[section].keys())[:5]:
            if tbl != tbl.upper():
                errors.append(f"{section}: table '{tbl}' not uppercase")
                break

    return errors


# ═══════════════════════════════════════════════════════════════════════
# SUMMARY REPORT
# ═══════════════════════════════════════════════════════════════════════

def print_summary(tables: dict[str, TableInfo], fk_list: list[FKInfo],
                  domain: dict, catalog: dict):
    """Print a concise summary of what was generated."""
    total_cols = sum(len(t.columns) for t in tables.values())
    single_fks = [f for f in fk_list if not f.is_composite]
    composite_fks = [f for f in fk_list if f.is_composite]
    pk_tables = [t for t in tables.values() if t.pk_cols]
    check_tables = [t for t in tables.values() if t.checks]

    records = domain.get(DOMAIN_ROOT_KEY, [])
    fk_flagged = sum(1 for r in records if r.get("is_foreign_key") == "YES")
    pk_flagged = sum(1 for r in records if r.get("is_primary_key") == "YES")
    cats = sorted(set(r.get("category", "OTHER") for r in records))

    print("=" * 64)
    print("  generate_dataview_schema.py — Summary")
    print("=" * 64)
    print()
    print(f"  Source:")
    print(f"    Tables:           {len(tables)}")
    print(f"    Columns:          {total_cols}")
    print(f"    Tables with PK:   {len(pk_tables)}")
    print(f"    CHECK constraints:{sum(len(t.checks) for t in tables.values())}")
    print()
    print(f"  Foreign keys:")
    print(f"    Single-column:    {len(single_fks)}")
    print(f"    Composite:        {len(composite_fks)}")
    print(f"    Total:            {len(fk_list)}")
    print()

    if composite_fks:
        print(f"  Composite FKs (in catalog only, not domain):")
        for fk in composite_fks:
            cols = ", ".join(fk.child_cols)
            print(f"    {fk.child_table}({cols}) → {fk.parent_table}")
        print()

    print(f"  Domain JSON ({DOMAIN_ROOT_KEY}):")
    print(f"    Records:          {len(records)}")
    print(f"    PK-flagged cols:  {pk_flagged}")
    print(f"    FK-flagged cols:  {fk_flagged}  (single-col only)")
    print(f"    Categories:       {', '.join(cats)}")
    print()

    cat_fk = catalog.get("fk_constraints", {})
    cat_pk = catalog.get("table_pk", {})
    cat_cols = catalog.get("table_cols", {})
    cat_kind = catalog.get("table_kind", {})
    print(f"  FK Catalog JSON:")
    print(f"    Tables with FKs:  {len(cat_fk)}")
    print(f"    Total FK entries: {sum(len(v) for v in cat_fk.values())}")
    print(f"    Tables with PKs:  {len(cat_pk)}")
    print(f"    Tables with cols: {len(cat_cols)}")
    print(f"    Kinds:            {dict(sorted(((k, list(cat_kind.values()).count(k)) for k in set(cat_kind.values()))))}")
    print()


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--ddl", type=Path,
                        help="Path to SSMS-generated DDL .sql file")
    source.add_argument("--conn", type=str,
                        help="SQLAlchemy connection string for live DB introspection")
    ap.add_argument("--out-dir", type=Path, default=Path("schema_registry"),
                    help="Output directory (default: schema_registry)")
    ap.add_argument("--schemas", nargs="+", default=["dataview"],
                    help="Schema(s) to include (default: dataview)")
    args = ap.parse_args()

    include = set(s.lower() for s in args.schemas)

    if args.ddl:
        if not args.ddl.exists():
            print(f"ERROR: DDL file not found: {args.ddl}", file=sys.stderr)
            sys.exit(1)
        print(f"Parsing DDL: {args.ddl} (schemas: {', '.join(args.schemas)}) ...")
        tables, fk_list = parse_ddl(args.ddl, include)
    else:
        print(f"Connecting to DB (schemas: {', '.join(args.schemas)}) ...")
        try:
            tables, fk_list = parse_db(args.conn, include)
        except Exception as e:
            print(f"ERROR: DB connection failed: {e}", file=sys.stderr)
            sys.exit(1)

    if not tables:
        print("ERROR: No tables found. Check --schemas filter.", file=sys.stderr)
        sys.exit(1)

    # Generate both outputs
    domain_data = emit_domain_json(tables, fk_list)
    catalog_data = emit_fk_catalog_json(tables, fk_list)

    # Validate
    d_errors = validate_domain(domain_data)
    c_errors = validate_fk_catalog(catalog_data)
    all_errors = d_errors + c_errors

    if all_errors:
        print("\nVALIDATION ERRORS:", file=sys.stderr)
        for e in all_errors:
            print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(1)

    # Write files
    args.out_dir.mkdir(parents=True, exist_ok=True)
    domain_path = args.out_dir / "dataview_schema_domain.json"
    catalog_path = args.out_dir / "dataview_fk_catalog.json"

    domain_path.write_text(
        json.dumps(domain_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    catalog_path.write_text(
        json.dumps(catalog_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Report
    print_summary(tables, fk_list, domain_data, catalog_data)
    print(f"  Written:")
    print(f"    {domain_path}")
    print(f"    {catalog_path}")
    print()
    print("  Validation: PASS")
    print("=" * 64)


if __name__ == "__main__":
    main()
