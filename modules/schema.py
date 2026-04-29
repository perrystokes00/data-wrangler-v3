"""
schema.py  —  PPDM Loader · Module 2: Schema Parser
=====================================================
Parses the PPDM 3.9 JSON schema catalog into typed Python objects.

Expected JSON format (one record per column):
{
  "ppdm_39_schema_domain": [
    {
      "model":            "PPDM 3.9",
      "category":         "ANL",
      "sub_category":     "anl_accuracy",
      "table_schema":     "dbo",
      "table_name":       "anl_accuracy",
      "column_name":      "accuracy_type",
      "data_type":        "nvarchar(40)",
      "not_null":         "YES",
      "is_primary_key":   "NO",
      "is_foreign_key":   "YES",
      "fk_table_schema":  "dbo",
      "fk_table_name":    "r_anl_accuracy_type",
      "fk_column_name":   "ACCURACY_TYPE",
      "check_constraints":"ANLA_CK: ([ACTIVE_IND]='N' OR [ACTIVE_IND]='Y') | ..."
    }, ...
  ]
}

Test:
    python schema.py
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# ROOT KEY — update this if your JSON uses a different top-level key
# ═══════════════════════════════════════════════════════════════════════

EXPECTED_ROOT_KEY = "ppdm_39_schema_domain"


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CheckConstraint:
    """A single parsed check constraint for one column."""
    name:           str
    column:         str          # lowercase column name
    allowed_values: list[str]


@dataclass
class ColumnDef:
    """All metadata for one PPDM table column."""
    table_schema:     str
    table_name:       str
    column_name:      str          # original case preserved
    data_type:        str          # e.g. "nvarchar(40)", "numeric(8,0)"
    not_null:         bool
    is_primary_key:   bool
    is_foreign_key:   bool
    fk_table_schema:  Optional[str]
    fk_table_name:    Optional[str]
    fk_column_name:   Optional[str]
    check_constraints: list[CheckConstraint] = field(default_factory=list)

    @property
    def allowed_values(self) -> list[str]:
        """Return allowed values from check constraints for this column, if any."""
        col_l = self.column_name.lower()
        for ck in self.check_constraints:
            if ck.column == col_l:
                return ck.allowed_values
        return []

    def __repr__(self) -> str:
        flags = []
        if self.is_primary_key: flags.append("PK")
        if self.is_foreign_key: flags.append(f"FK→{self.fk_table_name}.{self.fk_column_name}")
        if self.not_null:       flags.append("NOT NULL")
        tag = f" [{', '.join(flags)}]" if flags else ""
        return f"<Col {self.column_name} {self.data_type}{tag}>"


@dataclass
class TableDef:
    """All columns and metadata for one PPDM table."""
    table_schema: str
    table_name:   str
    category:     str
    sub_category: str
    columns:      list[ColumnDef] = field(default_factory=list)

    @property
    def pk_columns(self) -> list[ColumnDef]:
        return [c for c in self.columns if c.is_primary_key]

    @property
    def fk_columns(self) -> list[ColumnDef]:
        return [c for c in self.columns if c.is_foreign_key]

    @property
    def required_columns(self) -> list[ColumnDef]:
        return [c for c in self.columns if c.not_null]

    @property
    def column_names(self) -> list[str]:
        return [c.column_name for c in self.columns]

    def get_column(self, name: str) -> Optional[ColumnDef]:
        name_l = name.lower()
        for c in self.columns:
            if c.column_name.lower() == name_l:
                return c
        return None

    def __repr__(self) -> str:
        return (f"<Table {self.table_name} "
                f"cols={len(self.columns)} "
                f"pk={len(self.pk_columns)} "
                f"fk={len(self.fk_columns)}>")


@dataclass
class PPDMSchema:
    """Top-level container — all tables parsed from the JSON catalog."""
    tables:     dict[str, TableDef]          # lower table_name → TableDef
    categories: dict[str, list[str]]         # CATEGORY → [table_names]

    def get_table(self, name: str) -> Optional[TableDef]:
        return self.tables.get(name.lower())

    def table_names_for_category(self, category: str) -> list[str]:
        return self.categories.get(category.upper(), [])

    @property
    def all_table_names(self) -> list[str]:
        return sorted(self.tables.keys())

    @property
    def all_categories(self) -> list[str]:
        return sorted(self.categories.keys())

    def summary(self) -> str:
        total_cols = sum(len(t.columns) for t in self.tables.values())
        fk_cols    = sum(len(t.fk_columns) for t in self.tables.values())
        return (f"{len(self.tables)} tables · "
                f"{total_cols} columns · "
                f"{fk_cols} FK columns · "
                f"{len(self.categories)} categories")


# ═══════════════════════════════════════════════════════════════════════
# CONSTRAINT PARSER
# ═══════════════════════════════════════════════════════════════════════

def _parse_check_constraints(raw: Optional[str]) -> list[CheckConstraint]:
    """
    Parse PPDM check constraint string into CheckConstraint objects.

    Input example:
      "ANLA_CK: ([ACTIVE_IND]='N' OR [ACTIVE_IND]='Y') |
       ANLA_CK1: ([CALCULATED_IND]='N' OR [CALCULATED_IND]='Y')"
    """
    if not raw or not raw.strip():
        return []

    seen: dict[str, dict[str, set[str]]] = {}

    for part in raw.split("|"):
        part = part.strip()
        name_m  = re.match(r"^(\w+):", part)
        ck_name = name_m.group(1) if name_m else "UNKNOWN"
        hits    = re.findall(r"\[(\w+)\]='([^']+)'", part)

        for col, val in hits:
            col_l = col.lower()
            seen.setdefault(ck_name, {}).setdefault(col_l, set()).add(val)

    return [
        CheckConstraint(name=ck, column=col, allowed_values=sorted(vals))
        for ck, col_vals in seen.items()
        for col, vals in col_vals.items()
    ]


# ═══════════════════════════════════════════════════════════════════════
# DIAGNOSTIC HELPER — call this to understand what's in your JSON
# ═══════════════════════════════════════════════════════════════════════

def diagnose_json(raw: dict) -> dict:
    """
    Inspect a parsed JSON dict and return a diagnostic report.
    Useful for debugging why a schema file isn't loading correctly.

    Returns a dict with keys:
      - root_keys       : list of top-level keys found
      - found_root_key  : bool — was EXPECTED_ROOT_KEY present?
      - record_count    : int  — how many records in the array
      - sample_record   : dict — first record (to verify field names)
      - tables_found    : list[str] — distinct table_name values
      - missing_fields  : list[str] — required fields absent from sample
      - warnings        : list[str]
    """
    REQUIRED_FIELDS = [
        "table_name", "column_name", "data_type",
        "not_null", "is_primary_key", "is_foreign_key",
    ]

    root_keys   = list(raw.keys())
    records     = raw.get(EXPECTED_ROOT_KEY, [])
    found_root  = EXPECTED_ROOT_KEY in raw
    sample      = records[0] if records else {}
    tables      = sorted({r.get("table_name", "") for r in records if r.get("table_name")})
    missing     = [f for f in REQUIRED_FIELDS if f not in sample]
    warnings    = []

    if not found_root:
        warnings.append(
            f"Root key '{EXPECTED_ROOT_KEY}' not found. "
            f"Keys present: {root_keys}. "
            f"Update EXPECTED_ROOT_KEY in schema.py to match."
        )
    if not records:
        warnings.append("Record array is empty — nothing to parse.")
    if missing:
        warnings.append(f"Required fields missing from records: {missing}")
    if not tables:
        warnings.append("No table_name values found in records.")

    return {
        "root_keys":      root_keys,
        "found_root_key": found_root,
        "record_count":   len(records),
        "sample_record":  sample,
        "tables_found":   tables,
        "missing_fields": missing,
        "warnings":       warnings,
    }


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC LOADERS
# ═══════════════════════════════════════════════════════════════════════

def load_schema_from_file(path: str | Path) -> PPDMSchema:
    """Load and parse a PPDM JSON schema catalog from a file path."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return _build_schema(raw)


def load_schema_from_string(json_str: str) -> PPDMSchema:
    """Load and parse from a JSON string (e.g. from Streamlit file_uploader bytes)."""
    raw = json.loads(json_str)
    return _build_schema(raw)


def load_schema_from_dict(raw: dict) -> PPDMSchema:
    """Load and parse from an already-parsed dict."""
    return _build_schema(raw)


# ═══════════════════════════════════════════════════════════════════════
# CORE PARSER
# ═══════════════════════════════════════════════════════════════════════

def _build_schema(raw: dict) -> PPDMSchema:
    """Internal: parse raw dict into PPDMSchema. Raises ValueError on bad input."""

    # ── Locate the record array ─────────────────────────────────────
    records = raw.get(EXPECTED_ROOT_KEY)

    if records is None:
        diag = diagnose_json(raw)
        raise ValueError(
            f"Root key '{EXPECTED_ROOT_KEY}' not found in JSON.\n"
            f"Keys present: {diag['root_keys']}\n"
            f"Hint: update EXPECTED_ROOT_KEY in schema.py to match your file."
        )

    if not isinstance(records, list):
        raise ValueError(
            f"Expected '{EXPECTED_ROOT_KEY}' to be a JSON array, "
            f"got {type(records).__name__}."
        )

    if len(records) == 0:
        raise ValueError(
            f"'{EXPECTED_ROOT_KEY}' array is empty — no records to parse."
        )

    # ── Group records by table name ──────────────────────────────────
    table_records: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    for rec in records:
        tname = str(rec.get("table_name") or "").lower().strip()
        if tname:
            table_records[tname].append(rec)
        else:
            skipped += 1

    if not table_records:
        raise ValueError(
            "No records had a valid 'table_name' value. "
            "Check that your JSON uses the field name 'table_name'."
        )

    # ── Build TableDef objects ───────────────────────────────────────
    tables:     dict[str, TableDef]      = {}
    categories: dict[str, list[str]]     = defaultdict(list)

    for tname, recs in table_records.items():
        first   = recs[0]
        cat     = str(first.get("category")     or "").upper().strip() or "OTHER"
        sub     = str(first.get("sub_category") or "").lower().strip()
        tschema = str(first.get("table_schema") or "dbo").lower().strip()

        columns: list[ColumnDef] = []
        for rec in recs:
            col_name = str(rec.get("column_name") or "").strip()
            if not col_name:
                continue

            constraints = _parse_check_constraints(
                str(rec.get("check_constraints") or "")
            )

            col = ColumnDef(
                table_schema      = tschema,
                table_name        = tname,
                column_name       = col_name,
                data_type         = str(rec.get("data_type") or "nvarchar(max)").lower(),
                not_null          = str(rec.get("not_null",       "NO")).upper() == "YES",
                is_primary_key    = str(rec.get("is_primary_key", "NO")).upper() == "YES",
                is_foreign_key    = str(rec.get("is_foreign_key", "NO")).upper() == "YES",
                fk_table_schema   = rec.get("fk_table_schema") or None,
                fk_table_name     = rec.get("fk_table_name")   or None,
                fk_column_name    = rec.get("fk_column_name")  or None,
                check_constraints = constraints,
            )
            columns.append(col)

        tdef = TableDef(
            table_schema = tschema,
            table_name   = tname,
            category     = cat,
            sub_category = sub,
            columns      = columns,
        )
        tables[tname] = tdef

        if tname not in categories[cat]:
            categories[cat].append(tname)

    for cat in categories:
        categories[cat].sort()

    return PPDMSchema(tables=tables, categories=dict(categories))


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

_SAMPLE_JSON = {
    "ppdm_39_schema_domain": [
        {
            "model": "PPDM 3.9", "category": "ANL", "sub_category": "anl_accuracy",
            "table_schema": "dbo", "table_name": "anl_accuracy",
            "column_name": "accuracy_obs_no", "data_type": "numeric(8,0)",
            "not_null": "YES", "is_primary_key": "YES", "is_foreign_key": "NO",
            "fk_table_schema": None, "fk_table_name": None, "fk_column_name": None,
            "check_constraints": "ANLA_CK: ([ACTIVE_IND]='N' OR [ACTIVE_IND]='Y') | ANLA_CK4: ([REPORTED_IND]='N' OR [REPORTED_IND]='Y')"
        },
        {
            "model": "PPDM 3.9", "category": "ANL", "sub_category": "anl_accuracy",
            "table_schema": "dbo", "table_name": "anl_accuracy",
            "column_name": "accuracy_type", "data_type": "nvarchar(40)",
            "not_null": "NO", "is_primary_key": "NO", "is_foreign_key": "YES",
            "fk_table_schema": "dbo", "fk_table_name": "r_anl_accuracy_type",
            "fk_column_name": "ACCURACY_TYPE",
            "check_constraints": "ANLA_CK: ([ACTIVE_IND]='N' OR [ACTIVE_IND]='Y')"
        },
        {
            "model": "PPDM 3.9", "category": "ANL", "sub_category": "anl_accuracy",
            "table_schema": "dbo", "table_name": "anl_accuracy",
            "column_name": "active_ind", "data_type": "nvarchar(1)",
            "not_null": "NO", "is_primary_key": "NO", "is_foreign_key": "NO",
            "fk_table_schema": None, "fk_table_name": None, "fk_column_name": None,
            "check_constraints": "ANLA_CK: ([ACTIVE_IND]='N' OR [ACTIVE_IND]='Y')"
        },
        {
            "model": "PPDM 3.9", "category": "WELL", "sub_category": "well",
            "table_schema": "dbo", "table_name": "well",
            "column_name": "uwi", "data_type": "nvarchar(40)",
            "not_null": "YES", "is_primary_key": "YES", "is_foreign_key": "NO",
            "fk_table_schema": None, "fk_table_name": None, "fk_column_name": None,
            "check_constraints": ""
        },
        {
            "model": "PPDM 3.9", "category": "WELL", "sub_category": "well",
            "table_schema": "dbo", "table_name": "well",
            "column_name": "well_name", "data_type": "nvarchar(255)",
            "not_null": "NO", "is_primary_key": "NO", "is_foreign_key": "NO",
            "fk_table_schema": None, "fk_table_name": None, "fk_column_name": None,
            "check_constraints": ""
        },
    ]
}


if __name__ == "__main__":
    print("=" * 60)
    print("schema.py — self-test")
    print("=" * 60)

    # Test 1: Normal parse
    print("\n[TEST 1] Parse sample JSON")
    schema = load_schema_from_dict(_SAMPLE_JSON)
    print(f"  Summary : {schema.summary()}")
    print(f"  Tables  : {schema.all_table_names}")
    print(f"  Categories: {schema.all_categories}")

    tbl = schema.get_table("anl_accuracy")
    assert tbl is not None, "anl_accuracy table not found"
    assert len(tbl.columns) == 3
    assert len(tbl.pk_columns) == 1
    assert len(tbl.fk_columns) == 1
    print(f"  anl_accuracy: {tbl}")
    for col in tbl.columns:
        print(f"    {col}  allowed={col.allowed_values}")

    # Test 2: FK lookup
    print("\n[TEST 2] FK column")
    fk_col = tbl.get_column("accuracy_type")
    assert fk_col.is_foreign_key
    assert fk_col.fk_table_name == "r_anl_accuracy_type"
    print(f"  FK OK: {fk_col}")

    # Test 3: Check constraint parse
    print("\n[TEST 3] Check constraints")
    active_col = tbl.get_column("active_ind")
    assert active_col.allowed_values == ["N", "Y"], active_col.allowed_values
    print(f"  active_ind allowed: {active_col.allowed_values}")

    # Test 4: Category filter
    print("\n[TEST 4] Category filter")
    well_tables = schema.table_names_for_category("WELL")
    assert "well" in well_tables
    print(f"  WELL tables: {well_tables}")

    # Test 5: Wrong root key → error with helpful message
    print("\n[TEST 5] Bad root key → descriptive error")
    try:
        load_schema_from_dict({"wrong_key": []})
        assert False, "Should have raised"
    except ValueError as e:
        print(f"  Got expected error: {e}")

    # Test 6: Diagnose
    print("\n[TEST 6] Diagnose a bad JSON")
    diag = diagnose_json({"wrong_key": [{"table_name": "foo", "column_name": "bar"}]})
    print(f"  Warnings: {diag['warnings']}")

    # Test 7: JSON round-trip via string
    print("\n[TEST 7] load_schema_from_string")
    schema2 = load_schema_from_string(json.dumps(_SAMPLE_JSON))
    assert schema2.summary() == schema.summary()
    print(f"  Round-trip OK: {schema2.summary()}")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)
