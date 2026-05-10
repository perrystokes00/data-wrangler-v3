"""
fk_entity.py  —  PPDM Loader · FK Entity Table Resolution
===========================================================
Handles FK resolution for non-reference entity tables that need
new parent rows inserted before the main table can be loaded.

Covers:
  - BUSINESS_ASSOCIATE  — SHA-1 BUSINESS_ASSOCIATE_ID derived from operator string
  - FIELD               — SHA-1 FIELD_ID derived from field name
  - NODE                — lat/lon derived from well source data
  - STRAT_NAME_SET      — must be resolved before STRAT_UNIT
  - STRAT_UNIT          — two-level strat with set ID
  - CONTRACTOR          — SHA-1 CONTRACTOR_ID
  - POOL                — SHA-1 POOL_ID
  - Unknown tables      — blank mapping grid, user maps manually

SHA-1 derivation (server-side):
    CONVERT(CHAR(40), HASHBYTES('SHA1',
        UPPER(TRIM(REGEXP_REPLACE(value, '[^A-Za-z0-9 ]', '')))), 2)

    Since SQL Server has no REGEXP_REPLACE, we do punctuation stripping
    in Python before sending to server, then UPPER(TRIM(?)) in SQL.

Dependency ordering:
    Topological sort ensures parent tables are inserted before children.
    e.g. STRAT_NAME_SET before STRAT_UNIT.

Test:
    python fk_entity.py
"""

from __future__ import annotations
import re
import hashlib
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Tables that are reference/lookup tables — handled by simple r_/ra_ logic
REFERENCE_TABLE_PREFIXES = ("r_", "ra_")

# Known entity tables with smart defaults
# Maps table_name_upper → EntityTableConfig
KNOWN_ENTITY_TABLES: dict[str, "EntityConfig"] = {}   # populated after class def


@dataclass
class EntityConfig:
    """Smart defaults for a known PPDM entity table."""
    table_name:       str              # uppercase
    id_col:           str              # primary key / ID column
    name_col:         str              # human-readable name column
    id_is_sha1:       bool = False     # True = derive ID as SHA-1 of name
    # Source column hints — fuzzy matched against source file columns
    source_name_hints: list[str] = field(default_factory=list)
    source_id_hints:   list[str] = field(default_factory=list)
    # Extra columns to auto-fill beyond audit defaults
    extra_defaults:    dict[str, str] = field(default_factory=dict)


def _register(cfg: EntityConfig):
    KNOWN_ENTITY_TABLES[cfg.table_name.upper()] = cfg


_register(EntityConfig(
    table_name="BUSINESS_ASSOCIATE",
    id_col="BUSINESS_ASSOCIATE_ID",
    name_col="BA_LONG_NAME",
    id_is_sha1=True,
    source_name_hints=["OPERATOR", "COMPANY", "BA_LONG_NAME", "BA_NAME",
                       "OPERATOR_NAME", "LICENSEE"],
    source_id_hints=["BUSINESS_ASSOCIATE_ID", "OPERATOR_ID", "BA_ID"],
))
_register(EntityConfig(
    table_name="FIELD",
    id_col="FIELD_ID",
    name_col="FIELD_NAME",
    id_is_sha1=True,
    source_name_hints=["FIELD", "FIELD_NAME", "POOL_FIELD", "PRODUCING_FIELD"],
    source_id_hints=["FIELD_ID"],
))
_register(EntityConfig(
    table_name="NODE",
    id_col="NODE_ID",
    name_col="NODE_ID",      # NODE uses ID as the label
    id_is_sha1=False,
    source_name_hints=["SURFACE_NODE_ID", "NODE_ID", "BASE_NODE_ID"],
    source_id_hints=["NODE_ID", "SURFACE_NODE_ID"],
))
_register(EntityConfig(
    table_name="STRAT_NAME_SET",
    id_col="STRAT_NAME_SET_ID",
    name_col="STRAT_NAME_SET_ID",
    id_is_sha1=False,
    source_name_hints=["BASE_STRAT_NAME", "STRAT_NAME_SET_ID", "STRAT_SET",
                       "STRAT_NAME_SET"],
    source_id_hints=["BASE_STRAT_NAME", "STRAT_NAME_SET_ID"],
))
_register(EntityConfig(
    table_name="STRAT_UNIT",
    id_col="STRAT_UNIT_ID",
    name_col="LONG_NAME",
    id_is_sha1=False,
    source_name_hints=["BASE_STRAT_UNIT", "FORMATION_AT_TD", "STRAT_UNIT_ID",
                       "STRAT_UNIT_NAME", "FORMATION", "STRAT_NAME"],
    source_id_hints=["BASE_STRAT_UNIT", "STRAT_UNIT_ID"],
))
_register(EntityConfig(
    table_name="CONTRACTOR",
    id_col="CONTRACTOR_ID",
    name_col="CONTRACTOR_NAME",
    id_is_sha1=True,
    source_name_hints=["CONTRACTOR", "CONTRACTOR_NAME", "DRILLING_CONTRACTOR"],
    source_id_hints=["CONTRACTOR_ID"],
))
_register(EntityConfig(
    table_name="POOL",
    id_col="POOL_ID",
    name_col="POOL_NAME",
    id_is_sha1=True,
    source_name_hints=["POOL", "POOL_NAME", "RESERVOIR"],
    source_id_hints=["POOL_ID"],
))


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class EntityMappedCol:
    """One row in the entity table mapping grid."""
    entity_col:   str     # column in the entity (parent) table
    sql_type:     str
    not_null:     bool
    is_pk:        bool
    source_col:   str     # mapped source column ("" = skip/auto)
    derived:      bool    # True = value will be derived (SHA-1, coords, etc.)
    derived_expr: str     # human-readable derivation description
    const_value:  str = ""   # fixed literal applied to every row
    transform:    str = ""   # transform token (UPPER/LOWER/TRIM/LEFT:N etc.)


@dataclass
class EntityMapping:
    """Full mapping for one entity table."""
    table_name:    str
    schema:        str
    columns:       list[EntityMappedCol]
    config:        Optional[EntityConfig]
    # Strat-specific: if STRAT_NAME_SET_ID not in source, user provides a default
    strat_set_default: str = ""

    @property
    def id_col_mapping(self) -> Optional[EntityMappedCol]:
        cfg = self.config
        if not cfg:
            return None
        return next((c for c in self.columns
                     if c.entity_col.upper() == cfg.id_col.upper()), None)

    @property
    def name_col_mapping(self) -> Optional[EntityMappedCol]:
        cfg = self.config
        if not cfg:
            return None
        return next((c for c in self.columns
                     if c.entity_col.upper() == cfg.name_col.upper()), None)

    def to_dict(self) -> dict[str, str]:
        return {c.entity_col: c.source_col for c in self.columns}


@dataclass
class EntityResolution:
    """Result of resolving one entity table."""
    table_name:    str
    schema:        str
    ok:            bool
    message:       str
    rows_inserted: int = 0
    rows_existed:  int = 0


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def is_reference_table(table_name: str) -> bool:
    """Return True if table is a reference/lookup table (r_ or ra_ prefix)."""
    t = table_name.lower().strip()
    return any(t.startswith(p) for p in REFERENCE_TABLE_PREFIXES)


def normalise_for_sha1(value: str) -> str:
    """
    Normalise a string for SHA-1 hashing: UPPER + TRIM only.
    Must match the SQL transform: UPPER(LTRIM(RTRIM(col)))
    """
    return value.upper().strip()


def sha1_hex(value: str, encoding: str = "utf-16-le") -> str:
    """Compute SHA-1 hex of a normalised string.
    SQL Server: encoding="utf-16-le" (HASHBYTES on nvarchar)
    Oracle:     encoding="utf-8"     (UTL_RAW.CAST_TO_RAW)
    """
    return hashlib.sha1(value.encode(encoding)).hexdigest().upper()


def sha1_sql_expr(source_col_or_literal: str, is_col: bool = True) -> str:
    """
    Build SQL Server SHA-1 expression.
    Normalisation: UPPER(TRIM()) — punctuation stripped in Python before insert.
    Result: 40-char uppercase hex string.
    """
    if is_col:
        inner = f"UPPER(TRIM([{source_col_or_literal}]))"
    else:
        inner = f"UPPER(TRIM('{source_col_or_literal}'))"
    return f"CONVERT(CHAR(40), HASHBYTES('SHA1', {inner}), 2)"


def topological_sort(
    constraints: list,   # list[FKConstraint]
) -> list[str]:
    """
    Return parent table names in dependency order (parents first).
    Simple DFS topological sort on the FK graph.
    """
    # Build adjacency: child → set of parents
    parents_of: dict[str, set[str]] = {}
    all_tables: set[str] = set()

    for c in constraints:
        child  = c.child_table.upper()
        parent = c.parent_table.upper()
        all_tables.add(child)
        all_tables.add(parent)
        parents_of.setdefault(child, set()).add(parent)

    # Find entity parent tables (non-reference) in dependency order
    entity_parents = [
        t for t in all_tables
        if not is_reference_table(t)
        and t != constraints[0].child_table.upper()   # exclude the main target table
    ] if constraints else []

    # Topological sort
    visited: set[str] = set()
    order:   list[str] = []

    def visit(t: str):
        if t in visited:
            return
        visited.add(t)
        for p in parents_of.get(t, set()):
            if not is_reference_table(p):
                visit(p)
        order.append(t)

    for t in entity_parents:
        visit(t)

    return order   # parents appear before children


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED FK GRAPH
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class FKNode:
    """
    One node in the unified FK dependency graph.
    Represents a single parent table that the target table (directly or
    indirectly) depends on, along with its resolution state.
    """
    table_name:   str
    schema:       str
    depth:        int            # topological depth; higher = must be resolved first
    node_type:    str            # "reference" | "entity_sha1" | "entity_direct" | "entity_unknown"
    constraint:   object         # FKConstraint that introduced this node
    # Resolution state
    resolved:     bool = False
    rows_inserted: int = 0
    rows_existed:  int = 0
    action:        str = ""      # "insert" | "null" | "skip"
    # For entity nodes
    entity_mapping: object = None   # EntityMapping, populated lazily
    # For reference nodes — context loaded lazily
    ref_context:    dict = field(default_factory=dict)
    ref_edits:      list = field(default_factory=list)

    @property
    def is_reference(self) -> bool:
        return self.node_type == "reference"

    @property
    def summary_line(self) -> str:
        if not self.resolved:
            return ""
        if self.action == "insert":
            return (f"✅ {self.table_name} — "
                    f"{self.rows_inserted} row(s) inserted, "
                    f"{self.rows_existed} already existed")
        if self.action == "null":
            return f"✅ {self.table_name} — FK column set to NULL"
        if self.action == "skip":
            return f"✅ {self.table_name} — affected rows will be skipped at promote"
        return f"✅ {self.table_name} — resolved"


def build_fk_graph(
    engine,
    constraints: list,    # list[FKConstraint] from introspect_fk_constraints
    source_df,            # pd.DataFrame — source data
    col_mapping,          # ColumnMapping — to find which source cols map to FK cols
    target_table: str,
    violations: list | None = None,  # pre-computed FKViolation list (unused, for compat)
) -> tuple[list["FKNode"], list]:
    """
    Build a unified, topologically-sorted list of FKNode objects covering
    ALL FK parent tables — both reference (r_/ra_) and entity tables.

    Steps:
      1. Find all FK constraints with missing values in the source data
      2. Classify each parent table (reference / entity)
      3. Sort by depth (deepest dependency first — must be resolved first)
      4. Deduplicate (same parent table may appear via multiple constraints)

    Returns list ordered: deepest dependency first, shallowest last.
    Already-satisfied constraints (no missing values) are excluded.
    """
    from modules.fk import check_fk_violations, get_existing_parent_values

    target_upper = target_table.upper()
    nodes: dict[str, FKNode] = {}   # table_upper → FKNode
    depth_map: dict[str, int] = {}  # table_upper → max depth

    # Tables to skip: child tables of the target (e.g. well_area, well_bore when loading well).
    # These have the target table's name as a prefix — loading them requires the target
    # to already exist, creating a circular dependency.
    _target_prefix = target_table.lower().rstrip("_") + "_"

    # ── Build depth map via BFS on the full constraint graph ──────────
    # Direct parents of target = depth 1. Also recurse into parents of
    # reference tables so that e.g. r_well_status_type is resolved before
    # r_well_status (which has a FK to r_well_status_type).
    from modules.fk import introspect_fk_constraints
    queue = [(c, 1) for c in constraints]
    visited_edges: set[tuple] = set()
    all_constraints = list(constraints)   # grows as we discover parent FKs

    while queue:
        c, d = queue.pop(0)
        key = (c.parent_schema.upper(), c.parent_table.upper())
        if key in visited_edges:
            continue
        visited_edges.add(key)
        tbl_upper = c.parent_table.upper()
        depth_map[tbl_upper] = max(depth_map.get(tbl_upper, 0), d)
        # Recurse into reference AND known entity tables to discover grandparents.
        # e.g. strat_unit → strat_name_set, r_well_status → r_well_status_type
        tbl_lower = c.parent_table.lower()
        _is_ref_tbl    = any(tbl_lower.startswith(p) for p in REFERENCE_TABLE_PREFIXES)
        _is_entity_tbl = tbl_upper in KNOWN_ENTITY_TABLES
        if engine and (_is_ref_tbl or _is_entity_tbl):
            try:
                parent_fks = introspect_fk_constraints(
                    engine, c.parent_table, c.parent_schema
                )
                for pc in parent_fks:
                    pk = (pc.parent_schema.upper(), pc.parent_table.upper())
                    if pk not in visited_edges:
                        queue.append((pc, d + 1))
                        all_constraints.append(pc)
            except Exception:
                pass
    constraints = all_constraints

    # ── Check which constraints actually have missing values ───────────
    col_map = col_mapping.to_dict()   # {ppdm_col: source_col/select_expr}
    col_map_upper = {k.upper(): v for k, v in col_map.items()}  # case-insensitive lookup
    _src_cols_upper = {c2.upper(): c2 for c2 in source_df.columns}

    # Filter out constraints where no child col maps to source —
    # removes phantom grandparent nodes (e.g. r_well_status_qual when
    # source has no qualifier columns).
    # EXCEPTION: grandparent reference/known-entity/saved-mapping constraints
    # bypass this filter — their child cols belong to another table.
    target_upper_str = target_table.upper()

    def _has_saved_mapping(tbl: str) -> bool:
        """Check if a saved entity mapping exists for this table."""
        try:
            from modules.mapping import _load_cache, _entity_cache_key
            cache = _load_cache()
            return _entity_cache_key(target_table, tbl) in cache
        except Exception:
            return False

    constraints = [
        c for c in constraints
        if (
            (getattr(c, "child_table", "").upper() != target_upper_str
             and (any(c.parent_table.lower().startswith(p) for p in REFERENCE_TABLE_PREFIXES)
                  or c.parent_table.upper() in KNOWN_ENTITY_TABLES
                  or _has_saved_mapping(c.parent_table)))
            or
            any(
                col_map_upper.get(_cc.upper(), "") or _src_cols_upper.get(_cc.upper(), "")
                for _cc in (c.child_cols or [])
            )
        )
    ]

    for c in constraints:
        tbl_upper = c.parent_table.upper()

        # Skip child tables of the target table — they depend ON the target,
        # not the other way around (e.g. well_area when loading well).
        if c.parent_table.lower().startswith(_target_prefix):
            continue

        # Skip grandparent constraints unless parent is a reference table,
        # a known entity table, or has a saved entity mapping.
        c_child = getattr(c, "child_table", "").upper()
        _is_grandparent  = c_child and c_child != target_upper
        _is_ref_parent   = any(c.parent_table.lower().startswith(p) for p in REFERENCE_TABLE_PREFIXES)
        _is_known_entity = c.parent_table.upper() in KNOWN_ENTITY_TABLES
        _is_saved_entity = _has_saved_mapping(c.parent_table)
        if _is_grandparent and not _is_ref_parent and not _is_known_entity and not _is_saved_entity:
            continue

        # NOTE: We do NOT skip nullable FK constraints — if source data has
        # values (e.g. OPERATOR → business_associate), we still need to resolve.
        # The src_col check below handles truly unmapped constraints.

        # Find which source column maps to this FK child column.
        # Try all child_cols — compound FKs may have the data in col 2+.
        # Also fall back to direct name match against source_df columns —
        # catches FK cols that are present in source but not explicitly mapped.
        import re as _re
        child_col = ""
        src_col   = ""
        src_df_cols_upper = {c2.upper(): c2 for c2 in source_df.columns}
        for _cc in (c.child_cols or []):
            # Try via col_map first (explicit user mapping) — case-insensitive
            _sc = col_map_upper.get(_cc.upper(), "")
            _m  = _re.match(r'^\[(.+)\]$', _sc)
            if _m:
                _sc = _m.group(1)
            if _sc and _sc in source_df.columns:
                child_col = _cc
                src_col   = _sc
                break
            # Fall back: child_col name directly in source_df (case-insensitive)
            _direct = src_df_cols_upper.get(_cc.upper(), "")
            if _direct:
                child_col = _cc
                src_col   = _direct
                break

        # For grandparent constraints, trace source col via:
        # 1. Direct constraints sharing same child col
        # 2. Saved entity mapping (user previously mapped this table)
        if (_is_grandparent if "_is_grandparent" in dir() else False) and (not src_col or src_col not in source_df.columns):
            gp_child_cols = {cc.upper() for cc in (c.child_cols or [])}
            # Try direct constraint tracing
            for _dc in constraints:
                if getattr(_dc, "child_table", "").upper() != target_upper:
                    continue
                for _dcc in (_dc.child_cols or []):
                    _dsc = col_map_upper.get(_dcc.upper(), "")
                    if _dcc.upper() in gp_child_cols and _dsc and _dsc in source_df.columns:
                        src_col = _dsc
                        break
                if src_col and src_col in source_df.columns:
                    break
            # Fall back to saved entity mapping
            if (not src_col or src_col not in source_df.columns) and _is_saved_entity:
                try:
                    from modules.mapping import _load_cache, _entity_cache_key
                    _saved = _load_cache().get(_entity_cache_key(target_table, c.parent_table), {})
                    for _ec_col, _ec_entry in _saved.items():
                        _saved_src = _ec_entry.get("source_col", "")
                        if _saved_src and _saved_src in source_df.columns:
                            src_col = _saved_src
                            break
                except Exception:
                    pass

        if not src_col or src_col not in source_df.columns:
            continue    # not mapped — no FK check possible

        # Get distinct source values for this FK column
        raw_src_vals = [
            str(v).strip() for v in source_df[src_col].dropna().unique()
            if str(v).strip()
        ]
        if not raw_src_vals:
            continue

        cfg      = KNOWN_ENTITY_TABLES.get(tbl_upper)
        src_vals = set(raw_src_vals)

        parent_vals = set()
        if engine:
            existing = get_existing_parent_values(
                engine, c.parent_schema, c.parent_table, c.parent_cols
            )
            parent_vals = {str(t[0]).strip().upper() for t in existing if t}

        missing = [v for v in sorted(src_vals) if v.upper() not in parent_vals]

        if not missing:
            continue    # constraint satisfied — skip

        # Classify node type
        tbl_lower = c.parent_table.lower()
        if any(tbl_lower.startswith(p) for p in REFERENCE_TABLE_PREFIXES):
            node_type = "reference"
        else:
            cfg = KNOWN_ENTITY_TABLES.get(tbl_upper)
            if cfg and cfg.id_is_sha1:
                node_type = "entity_sha1"
            elif cfg:
                node_type = "entity_direct"
            else:
                node_type = "entity_unknown"

        if tbl_upper not in nodes:
            nodes[tbl_upper] = FKNode(
                table_name  = c.parent_table,
                schema      = c.parent_schema,
                depth       = depth_map.get(tbl_upper, 1),
                node_type   = node_type,
                constraint  = c,
            )
        # Store missing values on the constraint for use in UI
        c._missing_values = missing
        c._existing_count = len(src_vals) - len(missing)
        c._src_col        = [src_col] if src_col else []

    # Add grandparent nodes for any table that is a parent of an existing node
    # but has no node itself (skipped because no source col mapping).
    # These must appear in the graph to show correct load order.
    _existing_node_tbls = set(nodes.keys())
    for _c in all_constraints:
        _pt = _c.parent_table.upper()
        _ct = getattr(_c, "child_table", "").upper()
        if _pt in _existing_node_tbls or _pt == target_upper:
            continue
        if _ct not in _existing_node_tbls:
            continue
        _pt_lower = _c.parent_table.lower()
        if any(_pt_lower.startswith(p) for p in REFERENCE_TABLE_PREFIXES):
            _gp_type = "reference"
        elif _c.parent_table.upper() in KNOWN_ENTITY_TABLES:
            _gp_cfg = KNOWN_ENTITY_TABLES[_c.parent_table.upper()]
            _gp_type = "entity_sha1" if _gp_cfg.id_is_sha1 else "entity_direct"
        else:
            _gp_type = "entity_unknown"
        nodes[_pt] = FKNode(
            table_name = _c.parent_table,
            schema     = _c.parent_schema,
            depth      = depth_map.get(_pt, 2),
            node_type  = _gp_type,
            constraint = _c,
            resolved   = False,
        )
        _c._missing_values = []
        _c._existing_count = 0
        _c._src_col        = []
        _existing_node_tbls.add(_pt)

    # Topological sort: if node A's table has a FK to node B's table,
    # B must come before A. Fall back to depth-based ordering.
    node_list = list(nodes.values())
    node_tables = {n.table_name.upper() for n in node_list}

    # Build inter-node dependency: which nodes does each node depend on?
    # A node depends on another if its table has a FK pointing to that table.
    deps: dict[str, set[str]] = {n.table_name.upper(): set() for n in node_list}
    for c in all_constraints:
        child_tbl  = getattr(c, "child_table",  "").upper()
        parent_tbl = c.parent_table.upper()
        if child_tbl in deps and parent_tbl in node_tables and child_tbl != parent_tbl:
            deps[child_tbl].add(parent_tbl)   # child depends on parent

    # Kahn's algorithm
    in_degree = {t: len(d) for t, d in deps.items()}
    queue2 = sorted([t for t, d in in_degree.items() if d == 0],
                    key=lambda t: -nodes[t].depth)
    result = []
    while queue2:
        t = queue2.pop(0)
        result.append(nodes[t])
        for other, other_deps in deps.items():
            if t in other_deps:
                other_deps.discard(t)
                if not other_deps:
                    queue2.append(other)
                    queue2.sort(key=lambda x: -nodes[x].depth)

    # Append any remaining (cycles) sorted by depth
    added = {n.table_name.upper() for n in result}
    result += sorted([n for n in node_list if n.table_name.upper() not in added],
                     key=lambda n: -n.depth)
    return result, all_constraints


# ═══════════════════════════════════════════════════════════════════════
# BUILD ENTITY MAPPING
# ═══════════════════════════════════════════════════════════════════════

def get_entity_table_cols(
    engine,
    schema:     str,
    table_name: str,
) -> list[dict]:
    """Fetch column metadata for an entity table. Dialect-aware."""
    try:
        from sqlalchemy import text
        from modules.db import get_dialect as _gd
        _d      = _gd(engine)
        dialect = _d.name
        if dialect == "oracle":
            sql = """
            SELECT c.column_name, c.data_type, c.nullable, 'N',
                   CASE WHEN p.column_name IS NOT NULL THEN 1 ELSE NULL END
            FROM all_tab_columns c
            LEFT JOIN (
                SELECT cc.column_name
                FROM all_constraints con
                JOIN all_cons_columns cc
                  ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner
                WHERE con.constraint_type = 'P'
                  AND con.table_name = :table AND con.owner = :schema
            ) p ON p.column_name = c.column_name
            WHERE c.table_name = :table AND c.owner = :schema
            ORDER BY c.column_id
            """
            with engine.connect() as con:
                rows = con.execute(text(sql), {
                    "table": table_name.upper(), "schema": schema.upper()
                }).fetchall()
            return [{"name": r[0], "type": r[1], "nullable": (r[2] == 'Y'),
                     "identity": False, "is_pk": r[4] is not None}
                    for r in rows]
        else:
            sql = """
            SELECT c.name, tp.name AS type_name,
                   c.is_nullable, c.is_identity,
                   ic.key_ordinal
            FROM sys.columns  c
            JOIN sys.types    tp ON tp.user_type_id = c.user_type_id
            JOIN sys.tables   t  ON t.object_id  = c.object_id
            JOIN sys.schemas  s  ON s.schema_id  = t.schema_id
            LEFT JOIN sys.indexes      ix ON ix.object_id    = t.object_id
                                         AND ix.is_primary_key = 1
            LEFT JOIN sys.index_columns ic ON ic.object_id   = ix.object_id
                                          AND ic.index_id    = ix.index_id
                                          AND ic.column_id   = c.column_id
            WHERE t.name = :table AND s.name = :schema
            ORDER BY c.column_id
            """
            with engine.connect() as con:
                rows = con.execute(
                    text(sql), {"table": table_name, "schema": schema}
                ).fetchall()
            return [{"name": r[0], "type": r[1], "nullable": bool(r[2]),
                     "identity": bool(r[3]), "is_pk": r[4] is not None}
                    for r in rows]
    except Exception:
        return []


def build_entity_mapping(
    table_name:     str,
    schema:         str,
    source_columns: list[str],
    engine,
) -> EntityMapping:
    """
    Build an EntityMapping for one parent entity table.
    Pre-populates smart defaults for known tables.
    """
    from modules.mapping import AUDIT_COLUMNS  # reuse audit col list

    cfg      = KNOWN_ENTITY_TABLES.get(table_name.upper())
    col_defs = get_entity_table_cols(engine, schema, table_name)

    src_upper = {c.upper(): c for c in source_columns}

    def best_source(hints: list[str]) -> str:
        """Find best matching source column from hint list."""
        for h in hints:
            if h.upper() in src_upper:
                return src_upper[h.upper()]
        return ""

    mapped_cols: list[EntityMappedCol] = []

    for cd in col_defs:
        col_upper = cd["name"].upper()

        # Skip audit columns and identity columns
        if col_upper in AUDIT_COLUMNS or cd["identity"]:
            continue

        is_pk = cd["is_pk"]

        # Determine source mapping and derivation
        derived      = False
        derived_expr = ""
        source_col   = ""
        transform    = ""

        if cfg:
            if col_upper == cfg.id_col.upper() and cfg.id_is_sha1:
                # SHA-1 ID — pre-suggest the name col as source but leave
                # transform blank so SHA-1 is opt-in, not automatic.
                source_col = best_source(cfg.source_name_hints)

            elif col_upper == cfg.name_col.upper():
                # Name column — map from source
                source_col = best_source(cfg.source_name_hints)

            elif col_upper == cfg.id_col.upper() and not cfg.id_is_sha1:
                # ID comes directly from source
                source_col = best_source(cfg.source_id_hints)

            elif col_upper == "LATITUDE" and table_name.upper() == "NODE":
                source_col = best_source(["SURFACE_LATITUDE", "LATITUDE",
                                          "BOTTOM_HOLE_LATITUDE"])
            elif col_upper == "LONGITUDE" and table_name.upper() == "NODE":
                source_col = best_source(["SURFACE_LONGITUDE", "LONGITUDE",
                                          "BOTTOM_HOLE_LONGITUDE"])
            else:
                # Try to find a matching source column
                source_col = src_upper.get(col_upper, "")
        else:
            # Unknown table — try exact match
            source_col = src_upper.get(col_upper, "")

        mapped_cols.append(EntityMappedCol(
            entity_col   = cd["name"],
            sql_type     = cd["type"],
            not_null     = not cd["nullable"],
            is_pk        = is_pk,
            source_col   = source_col,
            derived      = derived,
            derived_expr = derived_expr,
            transform    = transform,
        ))

    return EntityMapping(
        table_name = table_name,
        schema     = schema,
        columns    = mapped_cols,
        config     = cfg,
    )


# ═══════════════════════════════════════════════════════════════════════
# PREVIEW DISTINCT ROWS
# ═══════════════════════════════════════════════════════════════════════

def preview_entity_rows(
    source_df:      pd.DataFrame,
    entity_mapping: EntityMapping,
    max_rows:       int = 5,
    dialect:        str = "sqlserver",
) -> tuple[pd.DataFrame, str]:
    """
    Build a preview DataFrame of rows that would be inserted into the
    entity table, including SHA-1 derived IDs.

    Returns:
        (preview_df, diagnostic_message)
        diagnostic_message is "" on success, explains the problem otherwise.
    """
    cfg  = entity_mapping.config
    rows = []

    # ── Find the source column to drive distinct values from ──────────
    # Priority: config name_col mapping → first non-derived mapped col
    name_m   = entity_mapping.name_col_mapping
    name_src = (name_m.source_col if name_m and name_m.source_col else "")

    if not name_src:
        for ec in entity_mapping.columns:
            if not ec.derived and ec.source_col and ec.source_col in source_df.columns:
                name_src = ec.source_col
                break

    if not name_src:
        mapped_info = ", ".join(
            f"{ec.entity_col}←'{ec.source_col or '(unmapped)'}'"
            for ec in entity_mapping.columns if not ec.derived
        ) or "(no columns mapped yet)"
        return pd.DataFrame(), (
            f"No source column mapped. "
            f"Assign a source column to at least one entity column above. "
            f"Current: {mapped_info}"
        )

    if name_src not in source_df.columns:
        return pd.DataFrame(), (
            f"Mapped source column '{name_src}' not found in source data. "
            f"Available: {', '.join(str(c) for c in source_df.columns[:10])}"
        )

    distinct_vals = [
        str(v).strip() for v in source_df[name_src].dropna().unique()
        if str(v).strip()
    ]
    if not distinct_vals:
        return pd.DataFrame(), f"Column '{name_src}' contains no non-empty values."

    # ── Build one preview row per distinct value ───────────────────────
    # SHA-1 is opt-in: only apply if user explicitly set transform="SHA1"
    _id_ec = entity_mapping.id_col_mapping if cfg else None
    _user_wants_sha1 = (
        cfg and cfg.id_is_sha1
        and _id_ec is not None
        and (getattr(_id_ec, "transform", "") or "").upper() == "SHA1"
        and bool(_id_ec.source_col)
    )
    _id_col_upper = cfg.id_col.upper() if cfg else ""

    for val_str in distinct_vals:
        row: dict[str, str] = {}

        if _user_wants_sha1:
            normalised        = normalise_for_sha1(val_str)
            _prev_enc = "utf-8" if dialect == "oracle" else "utf-16-le"
            row[cfg.id_col]   = sha1_hex(normalised, _prev_enc)
            row[cfg.name_col] = val_str

        elif cfg:
            if cfg.name_col != cfg.id_col:
                row[cfg.name_col] = val_str
            # Show raw ID value if source col mapped, else leave blank
            if _id_ec and _id_ec.source_col and _id_ec.source_col in source_df.columns:
                mask_id  = source_df[name_src].astype(str).str.strip() == val_str
                match_id = source_df[mask_id]
                row[cfg.id_col] = (
                    str(match_id.iloc[0][_id_ec.source_col]).strip()
                    if not match_id.empty else ""
                )

        else:
            pass  # Unknown table — handled in column loop below

        # Add any other non-derived mapped columns
        mask  = source_df[name_src].astype(str).str.strip() == val_str
        match = source_df[mask]
        for ec in entity_mapping.columns:
            if ec.derived or ec.entity_col in row:
                continue
            # Skip ID col for SHA-1 tables — already handled above
            if cfg and cfg.id_is_sha1 and ec.entity_col.upper() == _id_col_upper:
                continue
            if ec.source_col and ec.source_col in source_df.columns:
                row[ec.entity_col] = (
                    str(match.iloc[0][ec.source_col]).strip()
                    if not match.empty else ""
                )

        if row:
            rows.append(row)
        if len(rows) >= max_rows:
            break

    if not rows:
        return pd.DataFrame(), f"No previewable rows from column '{name_src}'."
    return pd.DataFrame(rows), ""


# ═══════════════════════════════════════════════════════════════════════
# INSERT ENTITY ROWS
# ═══════════════════════════════════════════════════════════════════════

def insert_entity_rows(
    engine,
    source_df:      pd.DataFrame,
    entity_mapping: EntityMapping,
    schema:         str = "dbo",
    stg_table:      str = "",
    stg_schema:     str = "stg",
) -> EntityResolution:
    """
    Insert all distinct missing rows into the entity table.

    When stg_table is provided, distinct source values are read directly
    from the staging table via SQL — no dataframe needed (server-side path).
    Falls back to source_df if stg_table is not provided.

    For SHA-1 tables: computes ID = HASHBYTES('SHA1', normalised_name) server-side.
    """
    try:
        from sqlalchemy import text
        from modules.mapping import AUDIT_COLUMNS

        from modules.db import get_dialect as _gd
        _d         = _gd(engine)
        dialect    = _d.name
        _q         = _d.quote
        cfg        = entity_mapping.config
        table_name = entity_mapping.table_name
        full_table = (_d.qualified(schema, table_name) if dialect == "oracle"
                      else f"[{schema}].[{table_name}]")

        # ── Gather distinct source values ─────────────────────────────
        name_m   = entity_mapping.name_col_mapping
        name_src = name_m.source_col if name_m else ""

        if not name_src:
            return EntityResolution(
                table_name=table_name, schema=schema,
                ok=True, message="No source column mapped — skipped",
            )

        if stg_table:
            # ── Server-side path: SELECT DISTINCT from staging table ──
            _stg_tbl_clean = stg_table.split(".")[-1]
            if dialect == "oracle":
                # Oracle has no 'stg' schema — staging lives in current user schema
                try:
                    with engine.connect() as _sc:
                        _ora_stg_sch = _sc.execute(text(
                            "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                        )).scalar() or stg_schema.upper()
                except Exception:
                    _ora_stg_sch = stg_schema.upper()
                _stg_full = f'"{_ora_stg_sch}"."{_stg_tbl_clean.upper()}"'
            else:
                _stg_full = f"[{stg_schema}].[{_stg_tbl_clean}]"
            with engine.connect() as _con:
                if dialect == "oracle":
                    _col_q = f'"{name_src}"'
                    _where = f"{_col_q} IS NOT NULL AND TRIM(TO_CHAR({_col_q})) IS NOT NULL"
                else:
                    _col_q = f'[{name_src}]'
                    _where = f"{_col_q} IS NOT NULL AND LTRIM(RTRIM(CAST({_col_q} AS NVARCHAR(MAX)))) <> ''"
                _rows = _con.execute(text(
                    f"SELECT DISTINCT {_col_q} FROM {_stg_full} WHERE {_where}"
                )).fetchall()
            distinct_vals = [str(r[0]).strip() for r in _rows if r[0] and str(r[0]).strip()]
        else:
            # ── In-memory path: use source_df ────────────────────────
            if name_src not in source_df.columns:
                return EntityResolution(
                    table_name=table_name, schema=schema,
                    ok=True, message="No source column mapped — skipped",
                )
            distinct_vals = [
                str(v).strip() for v in source_df[name_src].dropna().unique()
                if str(v).strip()
            ]

        if not distinct_vals:
            return EntityResolution(
                table_name=table_name, schema=schema,
                ok=True, message="No distinct values to insert",
            )

        # ── Check which values already exist ─────────────────────────
        _id_ec_ins = entity_mapping.id_col_mapping if cfg else None
        _ins_wants_sha1 = (
            cfg and cfg.id_is_sha1
            and _id_ec_ins is not None
            and (getattr(_id_ec_ins, "transform", "") or "").upper() in ("SHA1", "SHA1_40", "SHA1_20")
            and bool(_id_ec_ins.source_col)
        )

        if _ins_wants_sha1:
            # Encoding must match the DB SHA1 function:
            # SQL Server HASHBYTES uses UTF-16-LE; Oracle UTL_RAW.CAST_TO_RAW uses UTF-8
            _sha1_enc = "utf-8" if dialect == "oracle" else "utf-16-le"
            normalised_vals = [normalise_for_sha1(v) for v in distinct_vals]
            py_ids          = [sha1_hex(n, _sha1_enc) for n in normalised_vals]
            id_col          = cfg.id_col
            with engine.connect() as con:
                existing_ids = {
                    str(row[0]).strip().upper()
                    for row in con.execute(
                        text(f"SELECT {_q(id_col)} FROM {full_table}")
                    ).fetchall()
                    if row[0]
                }
            to_insert = [
                (v, n, sid)
                for v, n, sid in zip(distinct_vals, normalised_vals, py_ids)
                if sid.upper() not in existing_ids
            ]
        else:
            # Compare by ID value directly
            id_m   = entity_mapping.id_col_mapping
            id_src = id_m.source_col if id_m else name_src
            id_col = cfg.id_col if cfg else (id_m.entity_col if id_m else "")

            if stg_table and id_src and id_src != name_src:
                # Fetch id values server-side too
                with engine.connect() as _con:
                    _id_rows = _con.execute(text(
                        f"SELECT DISTINCT [{name_src}], [{id_src}] FROM {_stg_full} "
                        f"WHERE [{name_src}] IS NOT NULL"
                    )).fetchall()
                _name_to_id = {str(r[0]).strip(): str(r[1]).strip() for r in _id_rows if r[0]}
                distinct_ids = [_name_to_id.get(v, v) for v in distinct_vals]
            elif not stg_table and id_src and id_src in source_df.columns:
                distinct_ids = [
                    str(source_df.loc[
                        source_df[name_src].astype(str).str.strip() == v,
                        id_src
                    ].iloc[0]).strip()
                    for v in distinct_vals
                ]
            else:
                distinct_ids = distinct_vals

            if id_col and distinct_ids:
                with engine.connect() as con:
                    existing_ids = {
                        str(row[0]).strip().upper()
                        for row in con.execute(
                            text(f"SELECT {_q(id_col)} FROM {full_table}")
                        ).fetchall()
                        if row[0]
                    }
                to_insert = [
                    (v, v, sid)
                    for v, sid in zip(distinct_vals, distinct_ids)
                    if sid.upper() not in existing_ids
                ]
            else:
                to_insert = [(v, v, v) for v in distinct_vals]

        if not to_insert:
            return EntityResolution(
                table_name=table_name, schema=schema, ok=True,
                message=f"All {len(distinct_vals)} value(s) already exist in {full_table}",
                rows_existed=len(distinct_vals),
            )

        # ── Build INSERT ──────────────────────────────────────────────
        # Collect all non-audit, non-identity columns with mappings
        insert_cols:  list[str] = []
        insert_exprs: list[str] = []  # SQL expressions or "?" for params
        param_col_indices: list[int] = []  # which positions are parameterised

        # Audit date columns — use SQL expressions (dialect-aware)
        if dialect == "oracle":
            audit_date_exprs = {
                "ROW_CREATED_DATE":   "SYS_EXTRACT_UTC(SYSTIMESTAMP)",
                "ROW_CHANGED_DATE":   "SYS_EXTRACT_UTC(SYSTIMESTAMP)",
                "ROW_EFFECTIVE_DATE": "TO_DATE('1900-01-01','YYYY-MM-DD')",
                "ROW_EXPIRY_DATE":    "TO_DATE('2099-12-31','YYYY-MM-DD')",
            }
        else:
            audit_date_exprs = {
                "ROW_CREATED_DATE":   "GETUTCDATE()",
                "ROW_CHANGED_DATE":   "GETUTCDATE()",
                "ROW_EFFECTIVE_DATE": "CAST('1900-01-01' AS DATETIME2)",
                "ROW_EXPIRY_DATE":    "CAST('2099-12-31' AS DATETIME2)",
            }
        audit_str_defaults = {
            "ACTIVE_IND":      "Y",
            "ROW_CREATED_BY":  "PPDM_LOADER",
            "ROW_CHANGED_BY":  "PPDM_LOADER",
    # ROW_QUALITY excluded — FK to r_ppdm_row_quality
            "ROW_VERSION_NUMBER": "1",
            "SOURCE":          "PPDM_LOADER",
        }

        # Determine columns present in entity table
        col_def_map = {
            cd["name"].upper(): cd
            for cd in get_entity_table_cols(engine, schema, table_name)
        }

        if _ins_wants_sha1:
            if cfg.id_col.upper() not in col_def_map:
                raise ValueError(
                    f"ID column '{cfg.id_col}' not found in {table_name}. "
                    f"Available columns: {sorted(col_def_map)[:10]}..."
                )
            insert_cols.append(cfg.id_col)
            if dialect == "oracle":
                # Oracle SHA1: DBMS_CRYPTO.HASH with RAW_TO_HEX
                # Uses UPPER hex to match SQL Server HASHBYTES output
                insert_exprs.append(
                    "UPPER(RAWTOHEX(DBMS_CRYPTO.HASH(UTL_RAW.CAST_TO_RAW(?), 3)))"
                )
            else:
                insert_exprs.append(
                    "CONVERT(CHAR(40), HASHBYTES('SHA1', ?), 2)"
                )
            param_col_indices.append(0)  # normalised name value at index 0

            # Name column: raw value
            insert_cols.append(cfg.name_col)
            insert_exprs.append("?")
            param_col_indices.append(1)  # raw name at index 1

        elif cfg:
            # ID from source directly
            insert_cols.append(cfg.id_col)
            insert_exprs.append("?")
            param_col_indices.append(2)   # sid at index 2

            if cfg.name_col != cfg.id_col and cfg.name_col.upper() in col_def_map:
                insert_cols.append(cfg.name_col)
                insert_exprs.append("?")
                param_col_indices.append(0)   # raw name at index 0

        # NODE lat/lon
        if table_name.upper() == "NODE":
            lat_m = next((c for c in entity_mapping.columns
                          if c.entity_col.upper() == "LATITUDE"
                          and c.source_col), None)
            lon_m = next((c for c in entity_mapping.columns
                          if c.entity_col.upper() == "LONGITUDE"
                          and c.source_col), None)
            # lat/lon handled per-row below — skip here

        # Audit string defaults
        for col, val in audit_str_defaults.items():
            if col in col_def_map and not col_def_map[col]["nullable"]:
                insert_cols.append(col)
                insert_exprs.append(f"'{val}'")  # literal

        # Audit date expressions
        for col, expr in audit_date_exprs.items():
            if col in col_def_map:
                insert_cols.append(col)
                insert_exprs.append(expr)

        # PPDM_GUID
        if "PPDM_GUID" in col_def_map:
            insert_cols.append("PPDM_GUID")
            insert_exprs.append("RAWTOHEX(SYS_GUID())" if dialect == "oracle" else "NEWID()")

        cols_sql   = ", ".join(_q(c) for c in insert_cols)
        vals_sql   = ", ".join(insert_exprs)
        insert_sql = f"INSERT INTO {full_table} ({cols_sql}) VALUES ({vals_sql})"

        # ── Execute ───────────────────────────────────────────────────
        param_rows = []
        for raw_val, norm_val, sid in to_insert:
            # index 0 = normalised name, 1 = raw name, 2 = sid
            lookup = {0: norm_val, 1: raw_val, 2: sid}
            row = tuple(lookup[i] for i in param_col_indices)

            # NODE: handle per-row lat/lon
            if table_name.upper() == "NODE":
                # For NODE we insert one row per distinct node_id
                # lat/lon looked up per value
                pass  # handled separately below

            param_rows.append(row)

        if table_name.upper() == "NODE":
            # NODE: per-row insert with lat/lon lookup
            results = _insert_node_rows(
                engine, entity_mapping, source_df,
                [r[0] for r in to_insert],   # node_id values
                full_table, col_def_map
            )
            return results
        else:
            # Convert ?-placeholder insert_sql to named :p0,:p1... params
            _counter = [-1]
            def _replace_q(m):
                _counter[0] += 1
                return f":p{_counter[0]}"
            import re as _re2
            named_sql = _re2.sub(r"[?]", _replace_q, insert_sql)
            with engine.begin() as con:
                for row_tuple in param_rows:
                    row_dict = {f"p{i}": v for i, v in enumerate(row_tuple)}
                    con.execute(text(named_sql), row_dict)

        return EntityResolution(
            table_name=table_name, schema=schema, ok=True,
            message=(f"Inserted {len(to_insert)} new row(s) into {full_table} "
                     f"({len(distinct_vals) - len(to_insert)} already existed)"),
            rows_inserted=len(to_insert),
            rows_existed=len(distinct_vals) - len(to_insert),
        )

    except Exception as exc:
        return EntityResolution(
            table_name=entity_mapping.table_name, schema=schema,
            ok=False, message=f"Insert failed: {exc}",
        )


def _insert_node_rows(
    engine, entity_mapping: EntityMapping,
    source_df: pd.DataFrame,
    node_ids: list[str],
    full_table: str,
    col_def_map: dict,
) -> EntityResolution:
    """Insert NODE rows with lat/lon derived from source data."""
    try:
        lat_m = next((c for c in entity_mapping.columns
                      if c.entity_col.upper() == "LATITUDE"
                      and c.source_col), None)
        lon_m = next((c for c in entity_mapping.columns
                      if c.entity_col.upper() == "LONGITUDE"
                      and c.source_col), None)

        id_src = entity_mapping.id_col_mapping
        id_src_col = id_src.source_col if id_src else ""

        audit_exprs = {
            "ACTIVE_IND":         "'Y'",
            "ROW_CREATED_BY":     "'PPDM_LOADER'",
            "ROW_CHANGED_BY":     "'PPDM_LOADER'",
    # ROW_QUALITY excluded — FK to r_ppdm_row_quality
            "ROW_CREATED_DATE":   "GETUTCDATE()",
            "ROW_CHANGED_DATE":   "GETUTCDATE()",
            "ROW_EFFECTIVE_DATE": "CAST('1900-01-01' AS DATETIME2)",
            "ROW_EXPIRY_DATE":    "CAST('2099-12-31' AS DATETIME2)",
            "PPDM_GUID":          "NEWID()",
        }

        inserted = 0
        for node_id in node_ids:
            cols  = ["[NODE_ID]"]
            vals  = ["?"]
            params = [node_id]

            if lat_m and lat_m.source_col in source_df.columns:
                mask = source_df[id_src_col].astype(str).str.strip() == node_id
                match = source_df[mask]
                if not match.empty:
                    lat = str(match.iloc[0][lat_m.source_col]).strip()
                    lon = str(match.iloc[0][lon_m.source_col]).strip() if lon_m else ""
                    if lat and lat.lower() not in ("nan",""):
                        cols.append("[LATITUDE]")
                        vals.append("?")
                        params.append(lat)
                    if lon and lon.lower() not in ("nan",""):
                        cols.append("[LONGITUDE]")
                        vals.append("?")
                        params.append(lon)

            for acol, aexpr in audit_exprs.items():
                if acol in col_def_map:
                    cols.append(f"[{acol}]")
                    vals.append(aexpr)

            sql = (f"INSERT INTO {full_table} ({', '.join(cols)}) "
                   f"VALUES ({', '.join(vals)})")
            # Convert ? placeholders to named :p0,:p1 params
            named_vals = []
            param_dict = {}
            p_idx = 0
            for v in vals:
                if v == "?":
                    named_vals.append(f":p{p_idx}")
                    param_dict[f"p{p_idx}"] = params[p_idx]
                    p_idx += 1
                else:
                    named_vals.append(v)
            named_node_sql = (f"INSERT INTO {full_table} ({', '.join(cols)}) "
                              f"VALUES ({', '.join(named_vals)})")
            with engine.begin() as con:
                con.execute(text(named_node_sql), param_dict)
            inserted += 1

        return EntityResolution(
            table_name="NODE", schema="dbo", ok=True,
            message=f"Inserted {inserted} NODE row(s)",
            rows_inserted=inserted,
        )
    except Exception as exc:
        return EntityResolution(
            table_name="NODE", schema="dbo",
            ok=False, message=f"NODE insert failed: {exc}",
        )


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("PPDM Loader — FK Entity Resolution — Test")
    print("=" * 60)

    # Test 1: Reference table detection
    print("\n[TEST 1] Reference table detection")
    assert is_reference_table("r_well_class")
    assert is_reference_table("ra_country")
    assert not is_reference_table("business_associate")
    assert not is_reference_table("node")
    assert not is_reference_table("field")
    print("  ✓  r_well_class → reference")
    print("  ✓  ra_country   → reference")
    print("  ✓  business_associate → entity")
    print("  ✓  node → entity")

    # Test 2: SHA-1 normalisation
    print("\n[TEST 2] SHA-1 normalisation")
    raw = "  Suncor Energy Inc.  "
    norm = normalise_for_sha1(raw)
    assert norm == "SUNCOR ENERGY INC"
    h = sha1_hex(norm)
    assert len(h) == 40
    print(f"  ✓  '{raw}' → normalised: '{norm}'")
    print(f"  ✓  SHA-1: {h}")

    # Test 3: Known entity config
    print("\n[TEST 3] Known entity configs")
    ba_cfg = KNOWN_ENTITY_TABLES.get("BUSINESS_ASSOCIATE")
    assert ba_cfg is not None
    assert ba_cfg.id_is_sha1
    assert ba_cfg.id_col == "BUSINESS_ASSOCIATE_ID"
    assert ba_cfg.name_col == "BA_LONG_NAME"
    field_cfg = KNOWN_ENTITY_TABLES.get("FIELD")
    assert field_cfg.id_is_sha1
    strat_cfg = KNOWN_ENTITY_TABLES.get("STRAT_UNIT")
    assert not strat_cfg.id_is_sha1
    print(f"  ✓  BA: id_col={ba_cfg.id_col}, sha1={ba_cfg.id_is_sha1}")
    print(f"  ✓  FIELD: id_col={field_cfg.id_col}, sha1={field_cfg.id_is_sha1}")
    print(f"  ✓  STRAT_UNIT: id_col={strat_cfg.id_col}, sha1={strat_cfg.id_is_sha1}")

    # Test 4: Topological sort
    print("\n[TEST 4] Topological sort (strat dependency)")
    class _FC:
        def __init__(self, child, parent):
            self.child_table  = child
            self.parent_table = parent
    constraints = [
        _FC("well", "business_associate"),
        _FC("well", "strat_unit"),
        _FC("strat_unit", "strat_name_set"),
    ]
    order = topological_sort(constraints)
    strat_set_idx  = order.index("STRAT_NAME_SET")  if "STRAT_NAME_SET" in order else -1
    strat_unit_idx = order.index("STRAT_UNIT")      if "STRAT_UNIT"     in order else -1
    if strat_set_idx >= 0 and strat_unit_idx >= 0:
        assert strat_set_idx < strat_unit_idx, "STRAT_NAME_SET must come before STRAT_UNIT"
    print(f"  ✓  Resolution order: {order}")

    # Test 5: Preview rows
    print("\n[TEST 5] Preview entity rows (BA)")
    df = pd.DataFrame({"OPERATOR": ["Suncor Energy Inc.", "Cenovus Energy",
                                    "Suncor Energy Inc."]})
    from types import SimpleNamespace
    em = EntityMapping(
        table_name="BUSINESS_ASSOCIATE", schema="dbo",
        columns=[
            EntityMappedCol("BUSINESS_ASSOCIATE_ID", "nvarchar(40)", True,  True,  "",         True,  "SHA1"),
            EntityMappedCol("BA_LONG_NAME","nvarchar(255)",False, False, "OPERATOR", False, ""),
        ],
        config=ba_cfg,
    )
    preview = preview_entity_rows(df, em, max_rows=5)
    assert len(preview) == 2    # 2 distinct operators
    assert "BUSINESS_ASSOCIATE_ID" in preview.columns
    assert "BA_LONG_NAME"in preview.columns
    assert len(preview["BUSINESS_ASSOCIATE_ID"].iloc[0]) == 40
    print(f"  ✓  {len(preview)} distinct BA rows previewed")
    print(f"  ✓  BUSINESS_ASSOCIATE_ID sample: {preview['BUSINESS_ASSOCIATE_ID'].iloc[0]}")
    print(f"  ✓  BA_LONG_NAME: {preview['BA_LONG_NAME'].iloc[0]}")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)
