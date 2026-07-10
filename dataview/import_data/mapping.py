"""
mapping.py  —  PPDM Loader · Module 5: Match & Map
====================================================
Auto-matches source columns to PPDM target columns using fuzzy string
matching, then returns a ColumnMapping object that the UI can display
and the user can override.

Matching strategy (in priority order):
  1. Exact match (case-insensitive)
  2. Exact match after stripping common prefixes/suffixes
  3. Fuzzy token-sort ratio ≥ 70  (requires fuzzywuzzy)
  4. Fallback: no match (user must map manually)

Test:
    python mapping.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    from fuzzywuzzy import fuzz
    HAS_FUZZ = True
except ImportError:
    HAS_FUZZ = False


# ═══════════════════════════════════════════════════════════════════════
# AUDIT COLUMNS
# ═══════════════════════════════════════════════════════════════════════

# Standard PPDM audit columns — always filled by the app, never from source.
# These are excluded from the Match & Map grid entirely.
AUDIT_COLUMNS: dict[str, str] = {
    # Column name (upper)    : SQL expression or sentinel
    "PPDM_GUID":              "NEWID()",
    "ROW_CREATED_BY":         "'PPDM_LOADER'",
    "ROW_CHANGED_BY":         "'PPDM_LOADER'",
    "ROW_CREATED_DATE":       "GETUTCDATE()",
    "ROW_CHANGED_DATE":       "GETUTCDATE()",
    "ROW_EFFECTIVE_DATE":     "CAST('1900-01-01' AS DATETIME2)",
    "ROW_EXPIRY_DATE":        "CAST('2099-12-31' AS DATETIME2)",
    # ROW_QUALITY excluded — FK to r_ppdm_row_quality, must come from data
    "ACTIVE_IND":             "'Y'",
    "ROW_VERSION_NUMBER":     "1",
    "SOURCE":                 "'PPDM_LOADER'",
}


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

# ── Transform token format ──────────────────────────────────────────
# Stored in MappedColumn.transform as a short token string:
#   ""           — no transform, pass through as-is
#   "UPPER"      — UPPER([src])
#   "LOWER"      — LOWER([src])
#   "TRIM"       — TRIM([src])
#   "LEFT:N"     — LEFT([src], N)
#   "DATE:fmt"   — CONVERT(datetime2, [src], fmt)  e.g. DATE:103
#   "CASE:json"  — CASE [src] WHEN k THEN v ... END  (json = {k:v,...})
#   "SQL:expr"   — raw T-SQL with {col} placeholder  e.g. SQL:UPPER(TRIM({col}))

TRANSFORM_NONE   = ""
TRANSFORM_UPPER  = "UPPER"
TRANSFORM_LOWER  = "LOWER"
TRANSFORM_TRIM   = "TRIM"

TRANSFORM_OPTIONS = [
    "",
    "UPPER",
    "LOWER",
    "TRIM",
    "SHA1",      # CONVERT(CHAR(40), HASHBYTES('SHA1',...), 2)  — full 40-char hex
    "SHA1_20",   # LEFT(...SHA1..., 20)                         — first 20 chars
    "SHA1_40",   # same as SHA1 — explicit alias for clarity
]


def build_transform_sql(src_col: str, transform: str) -> str:
    """
    Convert a transform token + source column name into a T-SQL expression
    ready for use in a SELECT list.

    Examples:
        build_transform_sql("OPERATOR", "UPPER")   → "UPPER([OPERATOR])"
        build_transform_sql("TD",       "LEFT:40")  → "LEFT([TD], 40)"
        build_transform_sql("SPUD",     "DATE:103") → "CONVERT(datetime2,[SPUD],103)"
        build_transform_sql("STATUS",   "CASE:{...}")→ "CASE [STATUS] WHEN ... END"
        build_transform_sql("X",        "SQL:UPPER(TRIM({col}))")
                                                    → "UPPER(TRIM([X]))"
        build_transform_sql("NAME",     "")         → "[NAME]"
    """
    ref = f"[{src_col}]"
    if not transform:
        return ref
    t = transform.strip()
    if t in ("UPPER", "LOWER", "TRIM"):
        return f"{t}({ref})"
    if t.startswith("LEFT:"):
        n = t[5:].strip() or "40"
        return f"LEFT({ref}, {n})"
    if t.startswith("DATE:"):
        fmt = t[5:].strip() or "120"
        return f"CONVERT(datetime2, {ref}, {fmt})"
    if t.startswith("CASE:"):
        import json
        raw = t[5:].strip()
        try:
            mapping_dict = json.loads(raw) if raw and raw != "{}" else {}
        except Exception:
            mapping_dict = {}
        if not mapping_dict:
            return ref   # empty CASE — pass through
        when_clauses = " ".join(
            f"WHEN {_sql_literal(k)} THEN {_sql_literal(v)}"
            for k, v in mapping_dict.items()
        )
        return f"CASE {ref} {when_clauses} ELSE {ref} END"
    if t in ("SHA1", "SHA1_40"):
        # HASHBYTES on nvarchar uses UTF-16LE automatically — no CONVERT style needed
        return (f"CONVERT(CHAR(40), HASHBYTES('SHA1', "
                f"CAST(UPPER(LTRIM(RTRIM({ref}))) AS NVARCHAR(4000))), 2)")
    if t == "SHA1_20":
        return (f"LEFT(CONVERT(CHAR(40), HASHBYTES('SHA1', "
                f"CAST(UPPER(LTRIM(RTRIM({ref}))) AS NVARCHAR(4000))), 2), 20)")
    if t.startswith("SQL:"):
        expr = t[4:].strip()
        if not expr:
            return ref
        return expr.replace("{col}", ref)
    return ref   # unknown token — pass through


def _sql_literal(v: str) -> str:
    """Wrap a Python string as a SQL string literal, escaping single quotes."""
    return "'" + str(v).replace("'", "''") + "'"


@dataclass
class MappedColumn:
    """One row in the Match & Map table."""
    ppdm_col:     str                # target PPDM column name
    data_type:    str                # PPDM data type
    not_null:     bool
    is_pk:        bool
    is_fk:        bool
    fk_table:     Optional[str]
    source_col:     str                # "" = not mapped / skip
    match_score:    int                # 0-100; 100 = exact
    auto_matched:   bool               # True = system suggestion, False = user override
    auto_generated: bool = False       # True = server generates value (e.g. NEWID())
    auto_gen_expr:  str  = ""          # SQL expression e.g. "NEWID()"
    const_value:    str  = ""          # constant literal applied to every row
    transform:      str  = ""          # transform token (see TRANSFORM_OPTIONS)
    fk_samples:     list = field(default_factory=list)  # reserved, unused in grid
    explicitly_skipped: bool = False   # True = user deliberately cleared this column

    @property
    def is_mapped(self) -> bool:
        return bool(self.source_col) or bool(self.const_value) or self.auto_generated

    @property
    def select_expr(self) -> str:
        """
        The T-SQL SELECT expression for this column — used in promote INSERT..SELECT.
        Priority: auto_generated > constant > source+transform
        """
        if self.auto_generated:
            return self.auto_gen_expr
        if self.const_value and not self.source_col:
            return _sql_literal(self.const_value)
        if self.source_col:
            base = build_transform_sql(self.source_col, self.transform)
            if self.const_value:
                # Both set: use COALESCE(transform(src), constant)
                return f"COALESCE({base}, {_sql_literal(self.const_value)})"
            return base
        return "NULL"

    @property
    def match_label(self) -> str:
        if self.auto_generated:
            return "auto"
        if self.const_value and not self.source_col:
            return "const"
        if not self.source_col:
            return "—"
        label = ("exact"  if self.match_score == 100
                 else "strong" if self.match_score >= 80
                 else "fuzzy"  if self.match_score >= 60
                 else "manual")
        if self.transform:
            label += f"+{self.transform.split(':')[0].lower()}"
        return label


@dataclass
class ColumnMapping:
    """
    Full mapping between source and target columns for one load session.
    """
    target_table:   str
    source_columns: list[str]                     # columns available in source file
    mapped:         list[MappedColumn] = field(default_factory=list)

    # ── Convenience accessors ─────────────────────────────────────────

    @property
    def ppdm_columns(self) -> list[str]:
        return [m.ppdm_col for m in self.mapped]

    @property
    def active_pairs(self) -> list[tuple[str, str]]:
        """
        [(ppdm_col, select_expr)] for all user-mapped columns (non-auto-generated).
        select_expr includes any transform and/or constant, ready for INSERT..SELECT.
        Includes constant-only columns (no source_col required).
        """
        return [
            (m.ppdm_col, m.select_expr)
            for m in self.mapped
            if not m.auto_generated and m.is_mapped
        ]

    @property
    def auto_generated_cols(self) -> list[MappedColumn]:
        """Columns whose value is generated server-side (e.g. NEWID())."""
        # ROW_QUALITY excluded — FK to r_ppdm_row_quality, cannot be a literal
        _EXCLUDE = {"ROW_QUALITY"}
        return [m for m in self.mapped
                if m.auto_generated
                and getattr(m, "ppdm_col", "").upper() not in _EXCLUDE]

    @property
    def unmapped_required(self) -> list[MappedColumn]:
        """Required (NOT NULL / PK) columns with no source mapping and not auto-generated."""
        return [m for m in self.mapped
                if m.not_null and not m.source_col and not m.auto_generated]

    @property
    def mapped_count(self) -> int:
        return sum(1 for m in self.mapped if m.is_mapped)

    @property
    def required_count(self) -> int:
        return sum(1 for m in self.mapped if m.not_null)

    def get(self, ppdm_col: str) -> Optional[MappedColumn]:
        for m in self.mapped:
            if m.ppdm_col.lower() == ppdm_col.lower():
                return m
        return None

    def set_source(self, ppdm_col: str, source_col: str) -> None:
        """Update the source column for a given PPDM column (user override)."""
        for m in self.mapped:
            if m.ppdm_col.lower() == ppdm_col.lower():
                m.source_col        = source_col
                m.auto_matched      = False
                m.match_score       = 100 if source_col else 0
                # Track explicit un-mapping so it persists across sessions
                m.explicitly_skipped = (not source_col and not m.const_value)
                # If user maps a source column to a previously auto-generated
                # column (e.g. SOURCE as a PK), switch it to a real mapping
                if source_col and m.auto_generated:
                    m.auto_generated = False
                    m.auto_gen_expr  = ""
                return

    def set_const(self, ppdm_col: str, value: str) -> None:
        """Set or clear the constant value for a column."""
        for m in self.mapped:
            if m.ppdm_col.lower() == ppdm_col.lower():
                m.const_value = value
                return

    def set_transform(self, ppdm_col: str, transform: str) -> None:
        """Set the transform token for a column."""
        for m in self.mapped:
            if m.ppdm_col.lower() == ppdm_col.lower():
                m.transform = transform
                return

    def set_fk_samples(self, ppdm_col: str, samples: list) -> None:
        """Store FK sample values for display."""
        for m in self.mapped:
            if m.ppdm_col.lower() == ppdm_col.lower():
                m.fk_samples = samples[:5]
                return

    def to_dict(self) -> dict[str, str]:
        """Return {ppdm_col: source_col} dict for use in validation/promote."""
        return {m.ppdm_col: m.source_col for m in self.mapped}

    def to_const_dict(self) -> dict[str, str]:
        """Return {ppdm_col: const_value} for columns that have a constant set."""
        return {m.ppdm_col: m.const_value for m in self.mapped if m.const_value}

    def summary(self) -> str:
        total = len(self.mapped)
        mapped = self.mapped_count
        req = self.required_count
        unmapped_req = len(self.unmapped_required)
        return (
            f"Mapping: {mapped}/{total} columns mapped, "
            f"{req} required, {unmapped_req} required unmapped"
        )


# ═══════════════════════════════════════════════════════════════════════
# FUZZY SCORER
# ═══════════════════════════════════════════════════════════════════════

def _score(a: str, b: str) -> int:
    """Return 0-100 similarity score between two column name strings."""
    if not HAS_FUZZ:
        # Simple exact-after-normalize fallback
        return 100 if _normalize_name(a) == _normalize_name(b) else 0
    return max(
        fuzz.ratio(a.lower(), b.lower()),
        fuzz.token_sort_ratio(a.lower(), b.lower()),
        fuzz.partial_ratio(a.lower(), b.lower()),
    )


def _normalize_name(name: str) -> str:
    """Strip underscores, spaces, lowercase for comparison."""
    return re.sub(r"[_\s]", "", name).lower()


# ═══════════════════════════════════════════════════════════════════════
# AUTO-MATCH
# ═══════════════════════════════════════════════════════════════════════

def build_mapping(
    target_table: str,
    target_col_defs: list,           # list of ColumnDef from schema.py
    source_columns: list[str],
    min_score: int = 60,
) -> ColumnMapping:
    """
    Auto-match source columns to PPDM target columns.

    For each PPDM target column:
      1. Look for an exact case-insensitive match in source columns
      2. If none, try fuzzy matching; accept if score ≥ min_score
      3. If still none, leave unmapped (source_col = "")

    Args:
        target_table    : PPDM target table name
        target_col_defs : list of ColumnDef objects from schema.py
        source_columns  : list of column names from the source file
        min_score       : minimum fuzzy score to accept as a match (default 60)

    Returns:
        ColumnMapping ready for display and user editing
    """
    src_upper = [c.upper() for c in source_columns]
    src_norm  = {_normalize_name(c): c for c in source_columns}

    mapped: list[MappedColumn] = []

    for col_def in target_col_defs:
        ppdm = col_def.column_name.upper()

        # Audit columns are auto-filled by the app — skip from mapping grid
        # Exception: if the column is part of the PK it must be mappable
        # (e.g. SOURCE is a PK component in well_dir_srvy)
        if ppdm in AUDIT_COLUMNS and not col_def.is_primary_key:
            mapped.append(MappedColumn(
                ppdm_col      = col_def.column_name,
                data_type     = col_def.data_type,
                not_null      = col_def.not_null,
                is_pk         = col_def.is_primary_key,
                is_fk         = col_def.is_foreign_key,
                fk_table      = col_def.fk_table_name,
                source_col    = "",
                match_score   = 0,
                auto_matched  = False,
                auto_generated= True,
                auto_gen_expr = AUDIT_COLUMNS[ppdm],
            ))
            continue

        best_src   = ""
        best_score = 0
        auto       = True

        # Pass 1: exact match (case-insensitive)
        if ppdm in src_upper:
            best_src   = source_columns[src_upper.index(ppdm)]
            best_score = 100

        # Pass 2: normalized exact match
        elif _normalize_name(ppdm) in src_norm:
            best_src   = src_norm[_normalize_name(ppdm)]
            best_score = 95

        # Pass 3: fuzzy match
        else:
            for src in source_columns:
                s = _score(ppdm, src)
                if s > best_score:
                    best_score = s
                    best_src   = src
            if best_score < min_score:
                best_src   = ""
                best_score = 0

        mapped.append(MappedColumn(
            ppdm_col      = col_def.column_name,
            data_type     = col_def.data_type,
            not_null      = col_def.not_null,
            is_pk         = col_def.is_primary_key,
            is_fk         = col_def.is_foreign_key,
            fk_table      = col_def.fk_table_name,
            source_col    = best_src,
            match_score   = best_score,
            auto_matched  = auto and bool(best_src),
            auto_generated= False,
            auto_gen_expr = "",
        ))

    return ColumnMapping(
        target_table   = target_table,
        source_columns = source_columns,
        mapped         = mapped,
    )



# ═══════════════════════════════════════════════════════════════════════
# MAPPING FINGERPRINT  — save/restore mappings for repeated file formats
# ═══════════════════════════════════════════════════════════════════════

import hashlib, json
from pathlib import Path

_CACHE_FILE = Path(__file__).parent / "mapping_cache.json"


def _load_cache() -> dict:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"mapping_cache: saved to {_CACHE_FILE}")
    except Exception as e:
        print(f"mapping_cache: save failed: {e}")


def mapping_fingerprint(target_table: str, source_columns: list) -> str:
    key = target_table.upper() + "|" + ",".join(sorted(c.upper() for c in source_columns))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# Sentinel stored in cache to mark a column the user explicitly un-mapped.
# On restore, any column with this value will have auto-matching suppressed.
_SKIPPED_SENTINEL = "__skipped__"


def serialise_mapping(col_mapping) -> dict:
    """Serialise mapped columns plus any explicitly skipped ones."""
    result = {}
    for m in col_mapping.mapped:
        if m.auto_generated:
            continue
        if m.source_col or m.const_value:
            result[m.ppdm_col] = {
                "source_col":  m.source_col,
                "transform":   m.transform,
                "const_value": m.const_value,
            }
        elif getattr(m, "explicitly_skipped", False):
            # User deliberately cleared this column — save sentinel so
            # restore can suppress auto-matching on next load
            result[m.ppdm_col] = {
                "source_col":  _SKIPPED_SENTINEL,
                "transform":   "",
                "const_value": "",
            }
    return result


def save_mapping_to_disk(fingerprint: str, col_mapping) -> None:
    """Persist a serialised mapping to mapping_cache.json keyed by fingerprint."""
    cache = _load_cache()
    serialised = serialise_mapping(col_mapping)
    # Store target table name so batch loader can find mappings by table
    serialised['_meta'] = {
        'target_table': getattr(col_mapping, 'target_table', ''),
        'mapped_cols': [
            m.ppdm_col for m in col_mapping.mapped
            if m.source_col and not m.auto_generated
        ]
    }
    cache[fingerprint] = serialised
    _save_cache(cache)


def restore_mapping(col_mapping, saved: dict) -> int:
    """Apply a saved mapping dict onto a freshly built ColumnMapping."""
    src_set = {c.upper() for c in col_mapping.source_columns}
    restored = 0
    for m in col_mapping.mapped:
        if m.auto_generated:
            continue
        saved_entry = saved.get(m.ppdm_col)
        if not saved_entry:
            continue
        src   = saved_entry.get("source_col",  "")
        trans = saved_entry.get("transform",   "")
        const = saved_entry.get("const_value", "")
        # Sentinel — user explicitly un-mapped this column; suppress auto-match
        if src == _SKIPPED_SENTINEL:
            m.source_col        = ""
            m.transform         = ""
            m.const_value       = ""
            m.match_score       = 0
            m.auto_matched      = False
            m.explicitly_skipped = True
            restored += 1
            continue
        # Skip entries where nothing useful was saved
        if not src and not const:
            continue
        # Drop source col if it no longer exists in source columns,
        # but keep const_value if present
        if src and src.upper() not in src_set:
            src = ""
            if not const:
                continue
        m.source_col  = src
        m.transform   = trans
        m.const_value = const
        if src:
            m.match_score  = 100
            m.auto_matched = False
        restored += 1
    return restored


def restore_mapping_from_disk(col_mapping, fingerprint: str) -> int:
    """Look up fingerprint in mapping_cache.json and restore if found."""
    cache = _load_cache()
    saved = cache.get(fingerprint)
    if not saved:
        return 0
    return restore_mapping(col_mapping, saved)


# ── Entity mapping persistence ────────────────────────────────────────

def _entity_cache_key(target_table: str, entity_table: str) -> str:
    return f"entity:{target_table.upper()}:{entity_table.upper()}"


def save_entity_mapping(target_table: str, entity_mapping) -> None:
    """Persist an EntityMapping source column assignments to mapping_cache.json."""
    try:
        key = _entity_cache_key(target_table, entity_mapping.table_name)
        saved = {
            ec.entity_col: {
                "source_col":  ec.source_col,
                "const_value": ec.const_value,
                "transform":   ec.transform,
            }
            for ec in entity_mapping.columns
            if not ec.derived and (ec.source_col or ec.const_value)
        }
        if not saved:
            return
        cache = _load_cache()
        cache[key] = saved
        _save_cache(cache)
    except Exception as e:
        print(f"entity mapping save failed: {e}")


def restore_entity_mapping(target_table: str, entity_mapping, source_columns: list) -> int:
    """Restore a previously saved EntityMapping from mapping_cache.json.
    Only restores source_col if the column still exists in source_columns."""
    try:
        key = _entity_cache_key(target_table, entity_mapping.table_name)
        cache = _load_cache()
        saved = cache.get(key)
        if not saved:
            return 0
        src_upper = {c.upper() for c in source_columns}
        restored = 0
        for ec in entity_mapping.columns:
            entry = saved.get(ec.entity_col)
            if not entry:
                continue
            src = entry.get("source_col", "")
            if src and src.upper() not in src_upper:
                src = ""
            ec.source_col  = src
            ec.const_value = entry.get("const_value", "")
            ec.transform   = entry.get("transform",   "")
            if src or ec.const_value:
                restored += 1
        return restored
    except Exception as e:
        print(f"entity mapping restore failed: {e}")
        return 0

# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST  (run: python mapping.py)
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from dataview.core.schema import load_schema_from_string

    _SCHEMA_JSON = """
    {
      "ppdm_39_schema_domain": [
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"UWI",
         "data_type":"nvarchar(40)","not_null":"YES","is_primary_key":"YES",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":""},
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"WELL_NAME",
         "data_type":"nvarchar(255)","not_null":"NO","is_primary_key":"NO",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":""},
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"ACTIVE_IND",
         "data_type":"nvarchar(1)","not_null":"NO","is_primary_key":"NO",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":"WELL_CK: ([ACTIVE_IND]='N' OR [ACTIVE_IND]='Y')"},
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"SPUD_DATE",
         "data_type":"datetime","not_null":"NO","is_primary_key":"NO",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":""},
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"FINAL_TD",
         "data_type":"numeric(10,2)","not_null":"NO","is_primary_key":"NO",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":""},
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"OPERATOR_BA_ID",
         "data_type":"nvarchar(40)","not_null":"NO","is_primary_key":"NO",
         "is_foreign_key":"YES","fk_table_schema":"dbo","fk_table_name":"business_associate",
         "fk_column_name":"BA_ID","check_constraints":""}
      ]
    }
    """

    print("=" * 60)
    print("PPDM Loader — Module 5: Match & Map Test")
    print("=" * 60)

    schema = load_schema_from_string(_SCHEMA_JSON)
    tbl    = schema.get_table("well")

    # Test 1: Exact match
    print("\n[TEST 1] Exact column match")
    src_cols_exact = ["UWI", "WELL_NAME", "ACTIVE_IND", "SPUD_DATE", "FINAL_TD"]
    mapping = build_mapping("well", tbl.columns, src_cols_exact)
    uwi = mapping.get("UWI")
    assert uwi.source_col == "UWI"
    assert uwi.match_score == 100
    print(f"  ✓  UWI → '{uwi.source_col}' (score {uwi.match_score})")

    # Test 2: Fuzzy match with slight name difference
    print("\n[TEST 2] Fuzzy matching")
    src_cols_fuzzy = ["WELLID", "WELLNAME", "STATUS_IND", "DATE_SPUD", "TOTAL_DEPTH"]
    mapping2 = build_mapping("well", tbl.columns, src_cols_fuzzy, min_score=50)
    wname = mapping2.get("WELL_NAME")
    print(f"  ✓  WELL_NAME → '{wname.source_col}' (score {wname.match_score})")
    spud = mapping2.get("SPUD_DATE")
    print(f"  ✓  SPUD_DATE → '{spud.source_col}' (score {spud.match_score})")

    # Test 3: Unmapped required
    print("\n[TEST 3] Unmapped required columns")
    src_cols_missing = ["WELL_NAME", "ACTIVE_IND"]  # UWI (PK/required) missing
    mapping3 = build_mapping("well", tbl.columns, src_cols_missing)
    unmapped_req = mapping3.unmapped_required
    assert any(m.ppdm_col == "UWI" for m in unmapped_req), \
        "UWI should be in unmapped required"
    print(f"  ✓  Unmapped required: {[m.ppdm_col for m in unmapped_req]}")

    # Test 4: Manual override
    print("\n[TEST 4] Manual override")
    mapping.set_source("OPERATOR_BA_ID", "OPERATOR")
    op = mapping.get("OPERATOR_BA_ID")
    assert op.source_col == "OPERATOR"
    assert not op.auto_matched
    print(f"  ✓  OPERATOR_BA_ID manually set → '{op.source_col}'")

    # Test 5: to_dict
    print("\n[TEST 5] to_dict export")
    d = mapping.to_dict()
    assert d["UWI"] == "UWI"
    print(f"  ✓  {len(d)} entries in mapping dict")

    # Test 6: Summary
    print("\n[TEST 6] Summary")
    print(f"  ✓  {mapping.summary()}")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)
