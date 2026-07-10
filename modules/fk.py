"""
fk.py  —  PPDM Loader · Module 6: FK Resolution  (v2)
=======================================================
Proper FK resolution against a live SQL Server database.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class FKNode:
    """One node in the unified FK dependency graph."""
    table_name:    str
    schema:        str
    kind:          str          # "reference" | "entity"
    depth:         int
    constraint:    "FKConstraint | None" = None
    resolved:      bool   = False
    rows_inserted: int    = -1


def build_fk_dependency_graph(
    constraints: list["FKConstraint"],
    reference_prefixes: tuple[str, ...] = ("r_", "ra_"),
) -> list[FKNode]:
    if not constraints:
        return []
    parent_tables: dict[str, "FKConstraint"] = {}
    for c in constraints:
        key = c.parent_table.upper()
        if key not in parent_tables:
            parent_tables[key] = c
    depth: dict[str, int] = {k: 1 for k in parent_tables}
    known_deps = {
        "STRAT_UNIT":            "STRAT_NAME_SET",
        "WELL_LOG_CURVE":        "WELL_LOG",
        "WELL_DIR_SRVY_STATION": "WELL_DIR_SRVY",
    }
    changed = True
    while changed:
        changed = False
        for child, parent in known_deps.items():
            if child in depth and parent in depth:
                if depth[parent] <= depth[child]:
                    depth[parent] = depth[child] + 1
                    changed = True
    nodes: list[FKNode] = []
    for key, c in parent_tables.items():
        tname  = c.parent_table
        is_ref = any(tname.lower().startswith(p) for p in reference_prefixes)
        nodes.append(FKNode(
            table_name = tname,
            schema     = c.parent_schema,
            kind       = "reference" if is_ref else "entity",
            depth      = depth.get(key, 1),
            constraint = c,
        ))
    nodes.sort(key=lambda n: (-n.depth, 0 if n.kind == "reference" else 1, n.table_name))
    return nodes


@dataclass
class FKColumn:
    fk_col:   str
    ref_col:  str
    ordinal:  int
    nullable: bool = True   # is_nullable on the child column


@dataclass
class FKConstraint:
    constraint_name: str
    child_table:     str
    child_schema:    str
    parent_table:    str
    parent_schema:   str
    columns:         list[FKColumn]

    @property
    def child_cols(self) -> list[str]:
        return [c.fk_col for c in sorted(self.columns, key=lambda x: x.ordinal)]

    @property
    def parent_cols(self) -> list[str]:
        return [c.ref_col for c in sorted(self.columns, key=lambda x: x.ordinal)]

    @property
    def is_compound(self) -> bool:
        return len(self.columns) > 1

    @property
    def all_child_cols_nullable(self) -> bool:
        """True if every child column in this FK is nullable (optional reference)."""
        return all(c.nullable for c in self.columns)

    @property
    def parent_full(self) -> str:
        return f"[{self.parent_schema}].[{self.parent_table}]"

    @property
    def child_full(self) -> str:
        return f"[{self.child_schema}].[{self.child_table}]"

    @property
    def display_name(self) -> str:
        child_str  = ", ".join(self.child_cols)
        parent_str = ", ".join(self.parent_cols)
        return (f"{self.child_table}.({child_str}) → "
                f"{self.parent_table}.({parent_str})")


@dataclass
class ParentColDef:
    name:       str
    sql_type:   str
    nullable:   bool
    identity:   bool
    max_length: int


@dataclass
class FKViolation:
    constraint:       FKConstraint
    source_cols:      list[str]
    missing_values:   list[tuple]
    existing_count:   int
    rows_affected:    int
    resolved:         bool  = False
    action:           str   = ""
    required_cols:    list[ParentColDef] = field(default_factory=list)
    user_values:      dict[str, str]     = field(default_factory=dict)
    insert_count:     int   = 0


@dataclass
class FKIntrospectResult:
    ok:          bool
    message:     str
    constraints: list[FKConstraint]        = field(default_factory=list)
    parent_pks:  dict[str, list[str]]      = field(default_factory=dict)


@dataclass
class FKCheckResult:
    ok:          bool
    message:     str
    violations:  list[FKViolation]         = field(default_factory=list)
    constraints: list[FKConstraint]        = field(default_factory=list)

    @property
    def unresolved(self) -> list[FKViolation]:
        return [v for v in self.violations if not v.resolved]

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


# ═══════════════════════════════════════════════════════════════════════
# DB INTROSPECTION
# ═══════════════════════════════════════════════════════════════════════

def introspect_fk_constraints(
    engine,
    table_name: str,
    schema: str = "dbo",
) -> FKIntrospectResult:
    # ── Fast path: catalog lookup (no DB round-trip) ────────────
    # Wrapped in broad except — catalog module may not be installed yet
    try:
        import importlib as _il
        _fkc_mod = _il.import_module("modules.fk_catalog")
        _cat_result = _fkc_mod.get_catalog(engine).introspect(table_name, schema)
        if _cat_result is not None:
            return _cat_result
    except Exception:
        pass  # catalog unavailable -- fall through to live DB
    # ── Live DB introspection (fallback) ─────────────────────────
    try:
        from sqlalchemy import text
        from modules.db import get_dialect as _gd
        _d      = _gd(engine)
        dialect = _d.name

        if dialect == "oracle":
            # Resolve actual Oracle schema
            try:
                with engine.connect() as _sc:
                    schema = _sc.execute(text(
                        "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                    )).scalar() or schema.upper()
            except Exception:
                schema = schema.upper()

            fk_sql = """
            SELECT
                con.constraint_name             AS constraint_name,
                con.owner                       AS child_schema,
                con.table_name                  AS child_table,
                rcon.owner                      AS parent_schema,
                rcon.table_name                 AS parent_table,
                cc.column_name                  AS fk_col,
                pc.column_name                  AS ref_col,
                cc.position                     AS ordinal,
                CASE WHEN tc.nullable = 'Y' THEN 1 ELSE 0 END AS child_col_nullable
            FROM all_constraints con
            JOIN all_cons_columns cc
              ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner
            JOIN all_constraints rcon
              ON rcon.constraint_name = con.r_constraint_name AND rcon.owner = con.r_owner
            JOIN all_cons_columns pc
              ON pc.constraint_name = rcon.constraint_name AND pc.owner = rcon.owner
             AND pc.position = cc.position
            JOIN all_tab_columns tc
              ON tc.owner = con.owner
             AND tc.table_name = con.table_name
             AND tc.column_name = cc.column_name
            WHERE con.constraint_type = 'R'
              AND con.table_name = :table
              AND con.owner      = :schema
            ORDER BY con.constraint_name, cc.position
            """
            with engine.connect() as con:
                rows = con.execute(
                    text(fk_sql),
                    {"table": table_name.upper(), "schema": schema.upper()}
                ).fetchall()
        else:
            fk_sql = """
            SELECT
                fk.name                         AS constraint_name,
                cs.name                         AS child_schema,
                ct.name                         AS child_table,
                ps.name                         AS parent_schema,
                pt.name                         AS parent_table,
                cc.name                         AS fk_col,
                pc.name                         AS ref_col,
                fkc.constraint_column_id        AS ordinal,
                cc.is_nullable                  AS child_col_nullable
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns  fkc
                 ON fkc.constraint_object_id = fk.object_id
            JOIN sys.tables  ct  ON ct.object_id  = fk.parent_object_id
            JOIN sys.schemas cs  ON cs.schema_id  = ct.schema_id
            JOIN sys.columns cc  ON cc.object_id  = fk.parent_object_id
                                 AND cc.column_id = fkc.parent_column_id
            JOIN sys.tables  pt  ON pt.object_id  = fk.referenced_object_id
            JOIN sys.schemas ps  ON ps.schema_id  = pt.schema_id
            JOIN sys.columns pc  ON pc.object_id  = fk.referenced_object_id
                                 AND pc.column_id = fkc.referenced_column_id
            WHERE ct.name = :table
              AND cs.name = :schema
            ORDER BY fk.name, fkc.constraint_column_id
            """
            with engine.connect() as con:
                rows = con.execute(
                    text(fk_sql), {"table": table_name, "schema": schema}
                ).fetchall()

        constraints_map: dict[str, FKConstraint] = {}
        for row in rows:
            cname = row[0]
            if cname not in constraints_map:
                constraints_map[cname] = FKConstraint(
                    constraint_name = cname,
                    child_schema    = row[1],
                    child_table     = row[2],
                    parent_schema   = row[3],
                    parent_table    = row[4],
                    columns         = [],
                )
            constraints_map[cname].columns.append(
                FKColumn(fk_col=row[5], ref_col=row[6], ordinal=row[7],
                         nullable=bool(row[8]))
            )
        constraints = list(constraints_map.values())

        parent_tables  = list({c.parent_table  for c in constraints})
        parent_schemas = list({c.parent_schema for c in constraints})
        parent_pks: dict[str, list[str]] = {}

        if parent_tables:
            tbl_in = ", ".join(f"'{t}'" for t in parent_tables)
            sch_in = ", ".join(f"'{s}'" for s in parent_schemas)
            if dialect == "oracle":
                pk_sql = f"""
                SELECT con.owner, con.table_name, cc.column_name, cc.position
                FROM all_constraints con
                JOIN all_cons_columns cc
                  ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner
                WHERE con.constraint_type = 'P'
                  AND con.table_name IN ({tbl_in.upper()})
                  AND con.owner      IN ({sch_in.upper()})
                ORDER BY con.owner, con.table_name, cc.position
                """
            else:
                pk_sql = f"""
                SELECT s.name, t.name, c.name, ic.key_ordinal
                FROM sys.indexes        i
                JOIN sys.index_columns  ic ON ic.object_id = i.object_id
                                          AND ic.index_id  = i.index_id
                JOIN sys.columns        c  ON c.object_id  = i.object_id
                                          AND c.column_id  = ic.column_id
                JOIN sys.tables         t  ON t.object_id  = i.object_id
                JOIN sys.schemas        s  ON s.schema_id  = t.schema_id
                WHERE i.is_primary_key = 1
                  AND t.name IN ({tbl_in})
                  AND s.name IN ({sch_in})
                ORDER BY s.name, t.name, ic.key_ordinal
                """
            with engine.connect() as con:
                for row in con.execute(text(pk_sql)).fetchall():
                    key = f"{row[0]}.{row[1]}"
                    parent_pks.setdefault(key, []).append(row[2])

        return FKIntrospectResult(
            ok=True,
            message=(f"Found {len(constraints)} FK constraint(s) on "
                     f"{schema}.{table_name}"),
            constraints=constraints,
            parent_pks=parent_pks,
        )

    except Exception as exc:
        return FKIntrospectResult(
            ok=False, message=f"FK introspection failed: {exc}"
        )


def get_parent_col_defs(engine, parent_schema, parent_table) -> list[ParentColDef]:
    # ── Catalog fast path ────────────────────────────────────────
    try:
        import importlib as _il
        _fkc = _il.import_module("modules.fk_catalog").get_catalog(engine)
        if _fkc.available:
            _meta = _fkc.get_col_meta(parent_table)
            if _meta:
                return [ParentColDef(
                    name=col,
                    sql_type=info["type"],
                    nullable=info["nullable"],
                    identity=False,
                    max_length=info["max_length"],
                ) for col, info in _meta.items()]
    except Exception:
        pass
    # ── Live DB fallback ─────────────────────────────────────────
    try:
        from sqlalchemy import text
        from modules.db import get_dialect as _gd
        _d      = _gd(engine)
        dialect = _d.name
        if dialect == "oracle":
            sql = """
            SELECT column_name, data_type, nullable, 'N' AS is_identity, char_length
            FROM all_tab_columns
            WHERE table_name = :table AND owner = :schema
            ORDER BY column_id
            """
            with engine.connect() as con:
                rows = con.execute(text(sql), {
                    "table": parent_table.upper(),
                    "schema": parent_schema.upper()
                }).fetchall()
            return [ParentColDef(name=r[0], sql_type=r[1],
                                 nullable=(r[2] == 'Y'), identity=False,
                                 max_length=r[4] or 0)
                    for r in rows]
        else:
            sql = """
            SELECT c.name, tp.name AS type_name,
                   c.is_nullable, c.is_identity, c.max_length
            FROM sys.columns  c
            JOIN sys.types    tp ON tp.user_type_id = c.user_type_id
            JOIN sys.tables   t  ON t.object_id  = c.object_id
            JOIN sys.schemas  s  ON s.schema_id  = t.schema_id
            WHERE t.name = :table AND s.name = :schema
            ORDER BY c.column_id
            """
            with engine.connect() as con:
                rows = con.execute(
                    text(sql), {"table": parent_table, "schema": parent_schema}
                ).fetchall()
            return [ParentColDef(name=r[0], sql_type=r[1], nullable=bool(r[2]),
                                 identity=bool(r[3]), max_length=r[4])
                    for r in rows]
    except Exception:
        return []


# Module-level cache for parent values — persists for the lifetime of the process
_parent_values_cache: dict[str, set[tuple]] = {}

def get_existing_parent_values(engine, parent_schema, parent_table,
                                parent_cols, limit=50000,
                                check_values=None) -> set[tuple]:
    """
    Returns set of existing value tuples from the parent table.
    If check_values supplied (set of values to look up), only queries for
    those specific values — much faster than full table scan.
    """
    # Use targeted cache key when checking specific values
    if check_values and len(check_values) <= 500:
        _cv_key = "|".join(sorted(str(v) for v in check_values))
        cache_key = f"{parent_schema}.{parent_table}:{','.join(parent_cols)}:targeted:{hash(_cv_key)}"
    else:
        cache_key = f"{parent_schema}.{parent_table}:{','.join(parent_cols)}"

    if cache_key in _parent_values_cache:
        return _parent_values_cache[cache_key]
    try:
        from sqlalchemy import text
        from modules.db import get_dialect as _gd
        _d        = _gd(engine)
        dialect   = _d.name
        _q        = (lambda n: f'"{n.upper()}"') if dialect == "oracle" else (lambda n: f"[{n}]")
        _nolock   = "" if dialect == "oracle" else " WITH (NOLOCK)"
        _limit_kw = (lambda n: f"FETCH FIRST {n} ROWS ONLY") if dialect == "oracle" else (lambda n: f"TOP {n}")
        _tbl_full = (f'"{parent_schema.upper()}"."{parent_table.upper()}"' if dialect == "oracle"
                     else f"[{parent_schema}].[{parent_table}]")

        cols_sql = ", ".join(_q(c) for c in parent_cols)

        # Single-column FK with known values — use WHERE IN (fastest)
        if check_values and len(parent_cols) == 1 and len(check_values) <= 1000:
            placeholders = ", ".join(f":v{i}" for i in range(len(check_values)))
            # check_values may be 1-tuples like ("USA",) — bind the scalar inside,
            # not the tuple itself (binding a tuple errors → empty → false misses).
            params = {f"v{i}": (v[0] if isinstance(v, tuple) else v)
                      for i, v in enumerate(sorted(check_values))}
            sql = (f"SELECT DISTINCT {cols_sql} "
                   f"FROM {_tbl_full}{_nolock} "
                   f"WHERE {_q(parent_cols[0])} IN ({placeholders})")
            with engine.connect() as con:
                rows = con.execute(text(sql), params).fetchall()
        # Composite FK with known tuples — use OR conditions
        elif check_values and len(parent_cols) > 1 and len(check_values) <= 200:
            conditions, params = [], {}
            for i, val in enumerate(check_values):
                vals = val if isinstance(val, tuple) else (val,)
                col_conds = []
                for j, c in enumerate(parent_cols):
                    v = vals[j] if j < len(vals) else ""
                    if v == "":
                        col_conds.append(f"({_q(c)} IS NULL OR {_q(c)} = '')")
                    else:
                        col_conds.append(f"{_q(c)} = :cv{i}_{j}")
                        params[f"cv{i}_{j}"] = v
                conditions.append("(" + " AND ".join(col_conds) + ")")
            sql = (f"SELECT DISTINCT {cols_sql} "
                   f"FROM {_tbl_full}{_nolock} "
                   f"WHERE {' OR '.join(conditions)}")
            with engine.connect() as con:
                rows = con.execute(text(sql), params).fetchall()
        else:
            # Full scan fallback
            not_null = " AND ".join(f"{_q(c)} IS NOT NULL" for c in parent_cols)
            if dialect == "oracle":
                sql = (f"SELECT DISTINCT {cols_sql} "
                       f"FROM {_tbl_full} "
                       f"WHERE {not_null} "
                       f"FETCH FIRST {limit} ROWS ONLY")
            else:
                sql = (f"SELECT DISTINCT TOP {limit} {cols_sql} "
                       f"FROM {_tbl_full}{_nolock} "
                       f"WHERE {not_null}")
            with engine.connect() as con:
                rows = con.execute(text(sql)).fetchall()

        result = {tuple(str(v).strip() if v is not None else "" for v in row)
                  for row in rows}
        _parent_values_cache[cache_key] = result
        return result
    except Exception:
        return set()

def clear_parent_values_cache():
    """Call after inserting new rows into parent tables."""
    _parent_values_cache.clear()


def invalidate_parent_cache(parent_schema: str, parent_table: str):
    """Evict only the cache entries for a specific parent table.
    Call this immediately after inserting into that table so subsequent
    FK checks see the updated rows without clearing the entire cache.
    """
    prefix = f"{parent_schema}.{parent_table}:"
    stale  = [k for k in _parent_values_cache if k.startswith(prefix)]
    for k in stale:
        del _parent_values_cache[k]


def load_fk_samples_batch(engine, tables: list[str], schema="dbo", n=5) -> dict[str, list[str]]:
    """
    Load PK sample values for multiple FK parent tables in a minimal number of DB round trips.
    Returns {table_name: [sample_values]}.
    """
    if not tables:
        return {}
    from sqlalchemy import text
    from modules.db import get_dialect as _gd
    _d       = _gd(engine)
    dialect  = _d.name
    results  = {t: [] for t in tables}
    try:
        tbl_list = ", ".join(f"'{t.upper() if dialect == 'oracle' else t}'" for t in tables)

        if dialect == "oracle":
            # Resolve schema
            try:
                with engine.connect() as _sc:
                    schema = _sc.execute(text(
                        "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                    )).scalar() or schema.upper()
            except Exception:
                schema = schema.upper()

            pk_sql = f"""
                SELECT con.table_name, cc.column_name
                FROM all_constraints con
                JOIN all_cons_columns cc
                  ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner
                WHERE con.constraint_type = 'P'
                  AND cc.position = 1
                  AND con.owner = '{schema.upper()}'
                  AND con.table_name IN ({tbl_list})
            """
            with engine.connect() as con:
                pk_map = {row[0]: row[1] for row in con.execute(text(pk_sql)).fetchall()}

            # One query per table for Oracle (no UNION ALL with FETCH FIRST)
            for tbl in tables:
                pk_col = pk_map.get(tbl.upper())
                if pk_col:
                    try:
                        with engine.connect() as con:
                            rows = con.execute(text(
                                f'SELECT DISTINCT "{pk_col}" FROM "{schema}"."{tbl.upper()}" '
                                f'WHERE "{pk_col}" IS NOT NULL '
                                f'ORDER BY "{pk_col}" FETCH FIRST {n} ROWS ONLY'
                            )).fetchall()
                        results[tbl] = [str(r[0]).strip() for r in rows if r[0] is not None]
                    except Exception:
                        pass
        else:
            pk_sql = f"""
                SELECT t.name, c.name
                FROM sys.indexes      ix
                JOIN sys.index_columns ic ON ic.object_id = ix.object_id AND ic.index_id = ix.index_id
                JOIN sys.columns      c  ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                JOIN sys.tables       t  ON t.object_id = ix.object_id
                JOIN sys.schemas      s  ON s.schema_id = t.schema_id
                WHERE ix.is_primary_key = 1 AND ic.key_ordinal = 1
                  AND s.name = '{schema}' AND t.name IN ({tbl_list})
            """
            with engine.connect() as con:
                pk_map = {row[0]: row[1] for row in con.execute(text(pk_sql)).fetchall()}

            parts = []
            for tbl in tables:
                pk_col = pk_map.get(tbl)
                if pk_col:
                    parts.append(
                        f"SELECT '{tbl}' AS tbl, CAST([{pk_col}] AS NVARCHAR(500)) AS val "
                        f"FROM (SELECT DISTINCT TOP {n} [{pk_col}] FROM [{schema}].[{tbl}] WITH (NOLOCK) "
                        f"WHERE [{pk_col}] IS NOT NULL ORDER BY [{pk_col}]) _s{tbl}"
                    )
            if parts:
                union_sql = " UNION ALL ".join(parts)
                with engine.connect() as con:
                    for row in con.execute(text(union_sql)).fetchall():
                        tbl_name, val = row[0], row[1]
                        if val is not None:
                            results[tbl_name].append(str(val).strip())
    except Exception:
        pass
    return results


def load_fk_samples(engine, fk_table, fk_schema="dbo", n=5) -> list[str]:
    try:
        from sqlalchemy import text
        from modules.db import get_dialect as _gd
        _d      = _gd(engine)
        dialect = _d.name
        if dialect == "oracle":
            try:
                with engine.connect() as _sc:
                    fk_schema = _sc.execute(text(
                        "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                    )).scalar() or fk_schema.upper()
            except Exception:
                fk_schema = fk_schema.upper()
            pk_sql = """
                SELECT cc.column_name
                FROM all_constraints con
                JOIN all_cons_columns cc
                  ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner
                WHERE con.constraint_type = 'P'
                  AND con.table_name = :tbl AND con.owner = :sch
                ORDER BY cc.position
            """
            with engine.connect() as con:
                pk_rows = con.execute(text(pk_sql), {
                    "tbl": fk_table.upper(), "sch": fk_schema.upper()
                }).fetchall()
            if not pk_rows:
                return []
            pk_col = pk_rows[0][0]
            sample_sql = (f'SELECT DISTINCT "{pk_col}" '
                          f'FROM "{fk_schema}"."{fk_table.upper()}" '
                          f'WHERE "{pk_col}" IS NOT NULL '
                          f'ORDER BY "{pk_col}" FETCH FIRST {n} ROWS ONLY')
        else:
            pk_sql = """
                SELECT c.name
                FROM sys.indexes      ix
                JOIN sys.index_columns ic ON ic.object_id = ix.object_id
                                         AND ic.index_id  = ix.index_id
                JOIN sys.columns      c  ON c.object_id   = ic.object_id
                                         AND c.column_id  = ic.column_id
                JOIN sys.tables       t  ON t.object_id   = ix.object_id
                JOIN sys.schemas      s  ON s.schema_id   = t.schema_id
                WHERE ix.is_primary_key = 1
                  AND t.name = :tbl AND s.name = :sch
                ORDER BY ic.key_ordinal
            """
            with engine.connect() as con:
                pk_rows = con.execute(text(pk_sql), {"tbl": fk_table, "sch": fk_schema}).fetchall()
            if not pk_rows:
                return []
            pk_col = pk_rows[0][0]
            sample_sql = (f"SELECT DISTINCT TOP {n} [{pk_col}] "
                          f"FROM [{fk_schema}].[{fk_table}] "
                          f"WHERE [{pk_col}] IS NOT NULL "
                          f"ORDER BY [{pk_col}]")
        with engine.connect() as con:
            rows = con.execute(text(sample_sql)).fetchall()
        return [str(r[0]).strip() for r in rows if r[0] is not None]
    except Exception:
        return []


def get_required_non_pk_cols(col_defs, pk_cols) -> list[ParentColDef]:
    auto_handled = {
        "ACTIVE_IND", "ROW_CREATED_BY", "ROW_CHANGED_BY",
        "ROW_CREATED_DATE", "ROW_CHANGED_DATE",
        "ROW_EFFECTIVE_DATE", "ROW_EXPIRY_DATE", "ROW_QUALITY",
        "PPDM_GUID",
    }
    pk_upper = {c.upper() for c in pk_cols}
    return [c for c in col_defs
            if not c.nullable and not c.identity
            and c.name.upper() not in pk_upper
            and c.name.upper() not in auto_handled]


# ═══════════════════════════════════════════════════════════════════════
# FK CHECK
# ═══════════════════════════════════════════════════════════════════════

# Module-level cache for parent col defs
_parent_col_defs_cache: dict[str, list] = {}

def check_fk_violations(df, mapping, constraints, engine, parent_pks) -> FKCheckResult:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    violations: list[FKViolation] = []
    col_map   = mapping.to_dict()
    const_map = mapping.to_const_dict() if hasattr(mapping, "to_const_dict") else {}
    const_map_upper = {k.upper(): v for k, v in const_map.items()}

    # ── Step 1: collect all constraints that have mapped or constant cols ──
    work_items = []
    for constraint in constraints:
        # Skip constraints where all child columns are nullable —
        # missing parent = NULL on insert, not a data integrity violation.
        # Skip nullable FK constraints only for r_ reference tables —
        # entity parents (business_associate, field, etc.) are checked
        # even if nullable so violations are reported as warnings.
        if (constraint.all_child_cols_nullable
                and constraint.parent_table.lower().startswith('r_')):
            continue
        child_cols  = constraint.child_cols
        parent_cols = constraint.parent_cols

        src_cols   = []   # source df column name, or "" if constant/unmapped
        const_vals = []   # constant literal, or "" if mapped from df/unmapped

        for cc in child_cols:
            sc    = col_map.get(cc) or col_map.get(cc.upper()) or col_map.get(cc.lower())
            const = const_map_upper.get(cc.upper(), "")
            src_cols.append(sc or "")
            const_vals.append(const)

        # Skip if no column is either mapped to a source col or has a constant
        active_indices = [
            i for i, (sc, cv) in enumerate(zip(src_cols, const_vals))
            if (sc and sc in df.columns) or cv
        ]
        if not active_indices:
            continue

        # Reduce to only the active (mapped or constant) columns
        active_src_cols    = [src_cols[i]    for i in active_indices]
        active_const_vals  = [const_vals[i]  for i in active_indices]
        active_parent_cols = [parent_cols[i] for i in active_indices]

        # Build src tuples — vectorized for performance
        src_tuples: set[tuple] = set()
        if len(active_src_cols) == 1 and not active_const_vals[0]:
            # Fast path: single mapped column — no row iteration needed
            sc = active_src_cols[0]
            if sc and sc in df.columns:
                src_tuples = {
                    (str(v).strip(),)
                    for v in df[sc].dropna().unique()
                    if str(v).strip()
                }
        else:
            # Multi-column / constant path — vectorized with concat
            _col_series = []
            for sc, cv in zip(active_src_cols, active_const_vals):
                if cv:
                    _col_series.append(pd.Series([cv.strip()] * len(df), dtype=str))
                elif sc and sc in df.columns:
                    _col_series.append(df[sc].fillna("").astype(str).str.strip())
                else:
                    _col_series.append(pd.Series([""] * len(df), dtype=str))
            _combined = pd.concat(_col_series, axis=1)
            _combined.columns = range(len(_col_series))
            src_tuples = {
                tuple(row)
                for row in _combined.itertuples(index=False, name=None)
                if any(v for v in row)
            }

        if src_tuples:
            work_items.append((constraint, active_src_cols, active_parent_cols, src_tuples))

    if not work_items:
        return FKCheckResult(ok=True,
            message="FK check complete — 0 constraint(s) have missing values",
            violations=[], constraints=constraints)

    # ── Step 2: parallel DB lookups ──────────────────────────────
    def _check_one(item):
        constraint, src_cols, parent_cols, src_tuples = item
        existing = get_existing_parent_values(
            engine, constraint.parent_schema, constraint.parent_table,
            parent_cols, check_values=src_tuples)
        # Normalize to uppercase for comparison — SQL Server collation is
        # case-insensitive but Python set membership is not. Without this,
        # "Delineation" != "DELINEATION" → falsely flagged as missing → PK error.
        existing_upper = {tuple(v.upper() for v in t) for t in existing}
        missing = sorted(
            t for t in src_tuples
            if tuple(v.upper() for v in t) not in existing_upper
        )
        return constraint, src_cols, src_tuples, existing, missing

    results = []
    max_workers = min(8, len(work_items))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check_one, item): item for item in work_items}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                pass

    # ── Step 3: build violations from results ────────────────────
    for constraint, src_cols, src_tuples, existing, missing in results:
        existing_count = len(src_tuples) - len(missing)
        if not missing:
            continue

        rows_affected = 0
        for val_tuple in missing:
            mask = pd.Series([True] * len(df), index=df.index)
            for sc, v in zip(src_cols, val_tuple):
                if sc and sc in df.columns:   # skip constant/unmapped positions
                    mask &= df[sc].astype(str).str.strip().str.upper() == v.upper()
            rows_affected += int(mask.sum())

        parent_key = f"{constraint.parent_schema}.{constraint.parent_table}"
        pk_cols    = parent_pks.get(parent_key, constraint.parent_cols)

        # Cached col defs lookup
        if parent_key not in _parent_col_defs_cache:
            _parent_col_defs_cache[parent_key] = get_parent_col_defs(
                engine, constraint.parent_schema, constraint.parent_table)
        col_defs  = _parent_col_defs_cache[parent_key]
        req_cols  = get_required_non_pk_cols(col_defs, pk_cols)

        violations.append(FKViolation(
            constraint=constraint, source_cols=src_cols,
            missing_values=missing, existing_count=existing_count,
            rows_affected=rows_affected, required_cols=req_cols,
        ))

    return FKCheckResult(
        ok=True,
        message=f"FK check complete — {len(violations)} constraint(s) have missing values",
        violations=violations, constraints=constraints,
    )


def check_fk_violations_server(engine, stg_schema, stg_table,
                               mapping, constraints, parent_pks) -> FKCheckResult:
    """
    Server-side twin of check_fk_violations — produces identical FKViolation
    records WITHOUT pulling the staging table to the client.

    For each constraint, the distinct child value-tuples and their row counts
    come from a single GROUP BY against staging (one scan, only the distinct
    set crosses the wire); the parent side reuses get_existing_parent_values
    (already WHERE-IN server-side). This is the same set-based model the batch
    loader uses, so Stage 6 no longer depends on a 'SELECT * FROM staging' pull.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from sqlalchemy import text

    violations: list[FKViolation] = []
    col_map   = mapping.to_dict()
    const_map = mapping.to_const_dict() if hasattr(mapping, "to_const_dict") else {}
    const_map_upper = {k.upper(): v for k, v in const_map.items()}

    # Staging column set (case-insensitive) — one cheap catalog query.
    with engine.connect() as _c:
        _stg_cols = {r[0].lower() for r in _c.execute(text(
            "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(:t)"),
            {"t": f"{stg_schema}.{stg_table}"}).fetchall()}

    def _expr(sc: str, cv: str) -> str:
        if cv:
            return "'" + cv.strip().replace("'", "''") + "'"
        # CAST guards non-string staging columns; LTRIM/RTRIM mirrors .str.strip()
        return f"LTRIM(RTRIM(CAST([{sc}] AS NVARCHAR(4000))))"

    # ── Step 1: build one GROUP BY per eligible constraint ────────────
    work_items = []
    for constraint in constraints:
        if (constraint.all_child_cols_nullable
                and constraint.parent_table.lower().startswith('r_')):
            continue
        child_cols  = constraint.child_cols
        parent_cols = constraint.parent_cols

        src_cols, const_vals = [], []
        for cc in child_cols:
            sc    = col_map.get(cc) or col_map.get(cc.upper()) or col_map.get(cc.lower())
            const = const_map_upper.get(cc.upper(), "")
            src_cols.append(sc or "")
            const_vals.append(const)

        active = [
            i for i, (sc, cv) in enumerate(zip(src_cols, const_vals))
            if (sc and sc.lower() in _stg_cols) or cv
        ]
        if not active:
            continue

        a_src    = [src_cols[i]    for i in active]
        a_const  = [const_vals[i]  for i in active]
        a_parent = [parent_cols[i] for i in active]

        exprs   = [_expr(sc, cv) for sc, cv in zip(a_src, a_const)]
        sel     = ", ".join(f"{e} AS k{i}" for i, e in enumerate(exprs))
        grp     = ", ".join(exprs)
        non_empty = " OR ".join(f"({e} <> '')" for e in exprs)
        sql = (f"SELECT {sel}, COUNT(*) AS n "
               f"FROM [{stg_schema}].[{stg_table}] WITH (NOLOCK) "
               f"WHERE {non_empty} GROUP BY {grp}")
        work_items.append((constraint, a_src, a_parent, sql, len(exprs)))

    if not work_items:
        return FKCheckResult(ok=True,
            message="FK check complete — 0 constraint(s) have missing values",
            violations=[], constraints=constraints)

    # ── Step 2: parallel — one GROUP BY + one parent lookup each ───────
    def _check_one(item):
        constraint, src_cols, parent_cols, sql, ncols = item
        with engine.connect() as con:
            rows = con.execute(text(sql)).fetchall()
        tup_counts: dict[tuple, int] = {}
        for r in rows:
            tup = tuple((str(r[i]).strip() if r[i] is not None else "")
                        for i in range(ncols))
            if any(tup):
                tup_counts[tup] = tup_counts.get(tup, 0) + int(r[ncols])
        src_tuples = set(tup_counts.keys())
        existing = get_existing_parent_values(
            engine, constraint.parent_schema, constraint.parent_table,
            parent_cols, check_values=src_tuples)
        existing_upper = {tuple(v.upper() for v in t) for t in existing}
        missing = sorted(
            t for t in src_tuples
            if tuple(v.upper() for v in t) not in existing_upper)
        return constraint, src_cols, src_tuples, tup_counts, missing

    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(work_items))) as pool:
        futures = {pool.submit(_check_one, it): it for it in work_items}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception:
                pass

    # ── Step 3: build violations (identical shape to check_fk_violations) ──
    for constraint, src_cols, src_tuples, tup_counts, missing in results:
        if not missing:
            continue
        existing_count = len(src_tuples) - len(missing)
        rows_affected  = sum(tup_counts.get(t, 0) for t in missing)

        parent_key = f"{constraint.parent_schema}.{constraint.parent_table}"
        pk_cols    = parent_pks.get(parent_key, constraint.parent_cols)
        if parent_key not in _parent_col_defs_cache:
            _parent_col_defs_cache[parent_key] = get_parent_col_defs(
                engine, constraint.parent_schema, constraint.parent_table)
        col_defs = _parent_col_defs_cache[parent_key]
        req_cols = get_required_non_pk_cols(col_defs, pk_cols)

        violations.append(FKViolation(
            constraint=constraint, source_cols=src_cols,
            missing_values=missing, existing_count=existing_count,
            rows_affected=rows_affected, required_cols=req_cols,
        ))

    return FKCheckResult(
        ok=True,
        message=f"FK check complete — {len(violations)} constraint(s) have missing values",
        violations=violations, constraints=constraints,
    )

_NODE_LAT_COLS = ["SURFACE_LATITUDE", "BOTTOM_HOLE_LATITUDE", "LATITUDE", "LAT"]
_NODE_LON_COLS = ["SURFACE_LONGITUDE", "BOTTOM_HOLE_LONGITUDE", "LONGITUDE", "LON", "LONG"]


def derive_node_coords(node_id_val, node_id_src_col, source_df) -> dict[str, str]:
    coords: dict[str, str] = {}
    if not node_id_src_col or node_id_src_col not in source_df.columns:
        return coords
    mask    = source_df[node_id_src_col].astype(str).str.strip() == node_id_val
    matches = source_df[mask]
    if matches.empty:
        return coords
    first = matches.iloc[0]
    for lat_col in _NODE_LAT_COLS:
        if lat_col in source_df.columns:
            v = str(first.get(lat_col, "")).strip()
            if v and v.lower() not in ("nan", "none", ""):
                coords["LATITUDE"] = v
                break
    for lon_col in _NODE_LON_COLS:
        if lon_col in source_df.columns:
            v = str(first.get(lon_col, "")).strip()
            if v and v.lower() not in ("nan", "none", ""):
                coords["LONGITUDE"] = v
                break
    return coords


# ═══════════════════════════════════════════════════════════════════════
# PARENT TABLE INSERTION
# ═══════════════════════════════════════════════════════════════════════

_AUDIT_DEFAULTS = {
    "ACTIVE_IND":     "Y",
    "ROW_CREATED_BY": "PPDM_LOADER",
    "ROW_CHANGED_BY": "PPDM_LOADER",
    # ROW_QUALITY intentionally omitted — it is a FK to r_ppdm_row_quality
    # and 'LOADED' may not exist there. Map it explicitly if needed.
}
_AUDIT_DATE_DEFAULTS = {
    "ROW_CREATED_DATE":   "GETUTCDATE()",
    "ROW_CHANGED_DATE":   "GETUTCDATE()",
    "ROW_EFFECTIVE_DATE": "CAST('1900-01-01' AS DATETIME2)",
    "ROW_EXPIRY_DATE":    "CAST('2099-12-31' AS DATETIME2)",
}


def insert_missing_parent_rows(engine, violation, source_df) -> tuple[bool, str, int]:
    """Insert missing FK values as minimal rows into the parent table."""
    try:
        from sqlalchemy import text

        constraint    = violation.constraint
        parent_schema = constraint.parent_schema
        parent_table  = constraint.parent_table
        parent_cols   = constraint.parent_cols
        full_table    = constraint.parent_full
        source_cols   = violation.source_cols

        col_defs    = get_parent_col_defs(engine, parent_schema, parent_table)
        col_def_map = {c.name.upper(): c for c in col_defs}

        rows_to_insert = []
        for val_tuple in violation.missing_values:
            row: dict[str, object] = {}
            for pk_col, val in zip(parent_cols, val_tuple):
                row[pk_col.upper()] = val
            for col, val in violation.user_values.items():
                row[col.upper()] = val
            if parent_table.upper() == "NODE" and source_cols:
                coords = derive_node_coords(val_tuple[0], source_cols[0], source_df)
                row.update({k.upper(): v for k, v in coords.items()})
            for col, val in _AUDIT_DEFAULTS.items():
                if col in col_def_map and col not in row:
                    row[col] = val
            if "PPDM_GUID" in col_def_map and "PPDM_GUID" not in row:
                row["PPDM_GUID"] = "__NEWID__"
            rows_to_insert.append(row)

        if not rows_to_insert:
            return True, "No rows to insert", 0

        # Build column list from first row
        all_cols   = list(rows_to_insert[0].keys())
        param_cols = []   # columns that get named params
        val_parts  = []   # SQL expression per column

        for col in all_cols:
            if col in _AUDIT_DATE_DEFAULTS:
                val_parts.append(_AUDIT_DATE_DEFAULTS[col])
            elif col == "PPDM_GUID":
                val_parts.append("NEWID()")
            else:
                val_parts.append(None)   # placeholder — fill with named param
                param_cols.append(col)

        # Build named-param INSERT: :p0, :p1, ...
        named_vals = []
        p_idx = 0
        for part in val_parts:
            if part is None:
                named_vals.append(f":p{p_idx}")
                p_idx += 1
            else:
                named_vals.append(part)

        cols_sql   = ", ".join(f"[{c}]" for c in all_cols)
        insert_sql = f"INSERT INTO {full_table} ({cols_sql}) VALUES ({', '.join(named_vals)})"

        # Convert any residual ? placeholders to :pN named params
        import re as _re2
        _c2 = [-1]
        _named_sql = _re2.sub(r"[?]", lambda m: f":p{(_c2.__setitem__(0,_c2[0]+1) or _c2[0])}", insert_sql)

        with engine.begin() as con:
            for row in rows_to_insert:
                row_dict = {f"p{i}": row.get(col) for i, col in enumerate(param_cols)}
                con.execute(text(_named_sql), row_dict)

        return (True,
                f"Inserted {len(rows_to_insert)} row(s) into {full_table}",
                len(rows_to_insert))

    except Exception as exc:
        return False, f"Insert failed: {exc}", 0


# ═══════════════════════════════════════════════════════════════════════
# REFERENCE TABLE — SEED MISSING CODES
# ═══════════════════════════════════════════════════════════════════════

_AUDIT_COLS = {
    "ACTIVE_IND", "ROW_CREATED_BY", "ROW_CHANGED_BY", "ROW_QUALITY",
    "ROW_CREATED_DATE", "ROW_CHANGED_DATE", "ROW_EFFECTIVE_DATE",
    "ROW_EXPIRY_DATE", "PPDM_GUID", "ROW_VERSION_NUMBER", "SOURCE",
}

_AUDIT_EXPR = {
    "ACTIVE_IND":         "'Y'",
    "ROW_CREATED_BY":     "'PPDM_LOADER'",
    "ROW_CHANGED_BY":     "'PPDM_LOADER'",
    # ROW_QUALITY excluded — FK to r_ppdm_row_quality
    "ROW_VERSION_NUMBER": "1",
    "SOURCE":             "'PPDM_LOADER'",
    "ROW_CREATED_DATE":   "GETUTCDATE()",
    "ROW_CHANGED_DATE":   "GETUTCDATE()",
    "ROW_EFFECTIVE_DATE": "CAST('1900-01-01' AS DATETIME2)",
    "ROW_EXPIRY_DATE":    "CAST('2099-12-31' AS DATETIME2)",
    "PPDM_GUID":          "NEWID()",
}

_AUDIT_EXPR_ORACLE = {
    "ACTIVE_IND":         "'Y'",
    "ROW_CREATED_BY":     "'PPDM_LOADER'",
    "ROW_CHANGED_BY":     "'PPDM_LOADER'",
    "ROW_VERSION_NUMBER": "1",
    "SOURCE":             "'PPDM_LOADER'",
    "ROW_CREATED_DATE":   "SYS_EXTRACT_UTC(SYSTIMESTAMP)",
    "ROW_CHANGED_DATE":   "SYS_EXTRACT_UTC(SYSTIMESTAMP)",
    "ROW_EFFECTIVE_DATE": "TO_DATE('1900-01-01','YYYY-MM-DD')",
    "ROW_EXPIRY_DATE":    "TO_DATE('2099-12-31','YYYY-MM-DD')",
    "PPDM_GUID":          "RAWTOHEX(SYS_GUID())",
}


def get_reference_table_context(engine, violation) -> dict:
    try:
        from sqlalchemy import text
        c        = violation.constraint
        schema   = c.parent_schema
        table    = c.parent_table
        pk_cols  = c.parent_cols          # full list — handles compound PKs
        pk_col   = pk_cols[0]             # primary display column (backward compat)

        from modules.db import get_dialect as _gd
        _d      = _gd(engine)
        dialect = _d.name
        if dialect == "oracle":
            col_sql = """
                SELECT column_name, data_type, nullable, 'N'
                FROM all_tab_columns
                WHERE table_name = :tbl AND owner = :sch
                ORDER BY column_id
            """
            with engine.connect() as con:
                col_rows = con.execute(text(col_sql), {
                    "tbl": table.upper(), "sch": schema.upper()
                }).fetchall()
            all_cols = [{"name": r[0], "type": r[1], "nullable": (r[2] == 'Y'), "identity": False}
                        for r in col_rows]
        else:
            col_sql = """
                SELECT c.name, tp.name, c.is_nullable, c.is_identity
                FROM sys.columns c
                JOIN sys.types   tp ON tp.user_type_id = c.user_type_id
                JOIN sys.tables  t  ON t.object_id = c.object_id
                JOIN sys.schemas s  ON s.schema_id = t.schema_id
                WHERE t.name = :tbl AND s.name = :sch
                ORDER BY c.column_id
            """
            with engine.connect() as con:
                col_rows = con.execute(text(col_sql), {"tbl": table, "sch": schema}).fetchall()
            all_cols = [{"name": r[0], "type": r[1], "nullable": bool(r[2]), "identity": bool(r[3])}
                        for r in col_rows]

        pk_upper_set = {p.upper() for p in pk_cols}
        insertable   = [c["name"] for c in all_cols
                        if c["name"].upper() not in _AUDIT_COLS
                        and c["name"].upper() not in pk_upper_set
                        and not c["identity"]]

        name_col = pk_col
        for candidate in ["LONG_NAME", "SHORT_NAME", "REMARK", "DESCRIPTION"]:
            match = next((c["name"] for c in all_cols if candidate in c["name"].upper()), None)
            if match:
                name_col = match
                break
        if name_col == pk_col and insertable:
            name_col = insertable[0]

        # Display: all PK cols first, then insertable (non-audit, non-PK)
        display_cols = list(pk_cols) + [c for c in insertable if c not in pk_cols]
        if dialect == "oracle":
            cols_sql = ", ".join(f'"{c.upper()}"' for c in display_cols[:6])
            order_col = pk_cols[0]
            with engine.connect() as con:
                existing = con.execute(text(
                    f'SELECT {cols_sql} FROM "{schema.upper()}"."{table.upper()}" '
                    f'ORDER BY "{order_col.upper()}" FETCH FIRST 100 ROWS ONLY'
                )).fetchall()
        else:
            cols_sql  = ", ".join(f"[{c}]" for c in display_cols[:6])
            order_col = pk_cols[0]
            with engine.connect() as con:
                existing = con.execute(
                    text(f"SELECT TOP 100 {cols_sql} FROM [{schema}].[{table}] "
                         f"ORDER BY [{order_col}]")
                ).fetchall()

        existing_rows = [{display_cols[i]: (str(v).strip() if v is not None else "")
                          for i, v in enumerate(row)}
                         for row in existing]

        # Pre-build missing rows — map source cols (from violation) to parent PK cols
        # violation.missing_values tuples align with constraint child_cols → parent_cols
        # not necessarily with all pk_cols (compound PK may have extra cols not in FK)
        fk_child_cols  = violation.constraint.child_cols   # e.g. ["STATUS_TYPE_QUAL"]
        fk_parent_cols = violation.constraint.parent_cols  # e.g. ["STATUS_TYPE_QUAL"]
        missing_rows = []
        for tup in violation.missing_values:
            row = {}
            for i, pc in enumerate(fk_parent_cols):
                if i < len(tup):
                    row[pc] = str(tup[i]).strip()
            # Fill remaining PK cols (not covered by this FK) as empty — user fills them
            for pc in pk_cols:
                if pc not in row:
                    row[pc] = ""
            missing_rows.append(row)

        return {"pk_col":          pk_col,
                "pk_cols":         pk_cols,          # NEW — full PK col list
                "name_col":        name_col,
                "insertable_cols": insertable,
                "existing_rows":   existing_rows,
                "missing_rows":    missing_rows,     # NEW — pre-filled from source
                "display_cols":    display_cols[:6],
                "all_col_meta":    all_cols}

    except Exception as exc:
        return {"error": str(exc), "pk_col": "", "pk_cols": [], "name_col": "",
                "insertable_cols": [], "existing_rows": [], "missing_rows": [],
                "display_cols": []}


def insert_reference_rows(engine, violation, rows_to_insert, context) -> tuple[bool, str]:
    """Insert new codes into an r_/ra_ reference table using named params."""
    try:
        from sqlalchemy import text
        import sys

        c        = violation.constraint
        schema   = c.parent_schema
        table    = c.parent_table
        pk_col   = context["pk_col"]

        col_meta = {r["name"].upper(): r for r in context.get("all_col_meta", [])}

        if not rows_to_insert:
            return True, "Nothing to insert."

        inserted = 0
        skipped  = 0

        pk_cols        = context.get("pk_cols", [pk_col])   # compound PK support
        fk_parent_cols = violation.constraint.parent_cols   # cols the child FK actually references

        from modules.db import get_dialect as _gd
        _d       = _gd(engine)
        dialect  = _d.name
        _q       = _d.quote
        _tbl_fq  = (_d.qualified(schema, table) if dialect == "oracle"
                    else f"[{schema}].[{table}]")
        _audit   = _AUDIT_EXPR_ORACLE if dialect == "oracle" else _AUDIT_EXPR

        for row_vals in rows_to_insert:
            pk_vals = [str(row_vals.get(pc, "")).strip() for pc in pk_cols]
            if not all(pk_vals):
                skipped += 1
                continue

            fk_vals       = [str(row_vals.get(pc, "")).strip() for pc in fk_parent_cols]
            exists_conds  = " AND ".join(f"{_q(pc)} = :ck{i}" for i, pc in enumerate(fk_parent_cols))
            exists_sql    = f"SELECT 1 FROM {_tbl_fq} WHERE {exists_conds}"
            exists_params = {f"ck{i}": v for i, v in enumerate(fk_vals)}
            with engine.connect() as _chk:
                already_exists = _chk.execute(text(exists_sql), exists_params).fetchone() is not None
            if already_exists:
                skipped += 1
                continue

            tgt_cols   = [_q(pc) for pc in pk_cols]
            src_exprs  = [f":p{i}" for i in range(len(pk_cols))]
            param_dict = {f"p{i}": v for i, v in enumerate(pk_vals)}
            p_idx      = len(pk_cols)

            pk_col_set = {pc.upper() for pc in pk_cols}
            for col_name, val in row_vals.items():
                if col_name.upper() in pk_col_set:
                    continue
                col_upper = col_name.upper()
                if col_upper in _AUDIT_COLS:
                    continue
                if val is None or str(val).strip() == "":
                    continue
                meta = col_meta.get(col_upper, {})
                if meta.get("identity"):
                    continue
                tgt_cols.append(_q(col_name))
                src_exprs.append(f":p{p_idx}")
                param_dict[f"p{p_idx}"] = str(val).strip()
                p_idx += 1

            # Audit columns as SQL expressions (no params)
            for audit_col, expr in _audit.items():
                if audit_col.upper() in col_meta:
                    tgt_cols.append(_q(audit_col))
                    src_exprs.append(expr)

            insert_sql = (f"INSERT INTO {_tbl_fq} "
                          f"({', '.join(tgt_cols)}) "
                          f"VALUES ({', '.join(src_exprs)})")

            import re as _re
            _ctr = [-1]
            def _rq(m):
                _ctr[0] += 1
                return f":p{_ctr[0]}"
            _named_sql = _re.sub(r"[?]", _rq, insert_sql)
            with engine.begin() as con:
                con.execute(text(_named_sql), param_dict)
            inserted += 1

        msg = f"Inserted {inserted} new code(s) into {_tbl_fq}"
        if skipped:
            msg += f" ({skipped} skipped — empty code or already exists)"
        if inserted:
            invalidate_parent_cache(schema, table)
        return True, msg

    except Exception as exc:
        return False, f"Insert failed: {exc}"


# ═══════════════════════════════════════════════════════════════════════
# APPLY RESOLUTIONS
# ═══════════════════════════════════════════════════════════════════════

def apply_resolutions(df, violations) -> tuple:
    df = df.copy()
    skip_indices: set[int] = set()
    for v in violations:
        if not v.resolved or v.action == "skip":
            for val_tuple in v.missing_values:
                mask = _build_mask(df, v.source_cols, val_tuple)
                skip_indices.update(df[mask].index.tolist())
        elif v.action == "null":
            for val_tuple in v.missing_values:
                mask = _build_mask(df, v.source_cols, val_tuple)
                for sc in v.source_cols:
                    if sc in df.columns:
                        df.loc[mask, sc] = ""
    return df, skip_indices


def _build_mask(df, src_cols, vals):
    mask = pd.Series([True] * len(df), index=df.index)
    for sc, v in zip(src_cols, vals):
        if sc in df.columns:
            mask &= df[sc].astype(str).str.strip() == v
    return mask


# ═══════════════════════════════════════════════════════════════════════
# DEMO MODE
# ═══════════════════════════════════════════════════════════════════════

def introspect_fk_demo(table_name: str) -> FKIntrospectResult:
    if table_name.lower() != "well":
        return FKIntrospectResult(ok=True, message="Demo mode — no constraints simulated")
    demo = [
        FKConstraint("FK_WELL_BA", "dbo", "well", "dbo", "business_associate",
                     [FKColumn("OPERATOR", "BA_ID", 1)]),
        FKConstraint("FK_WELL_NODE_SURF", "dbo", "well", "dbo", "node",
                     [FKColumn("SURFACE_NODE_ID", "NODE_ID", 1)]),
        FKConstraint("FK_WELL_FIELD", "dbo", "well", "dbo", "field",
                     [FKColumn("FIELD_ID", "FIELD_ID", 1)]),
    ]
    return FKIntrospectResult(
        ok=True, message=f"Demo: {len(demo)} FK constraints", constraints=demo,
        parent_pks={"dbo.business_associate": ["BA_ID"],
                    "dbo.node": ["NODE_ID"], "dbo.field": ["FIELD_ID"]},
    )


# ═══════════════════════════════════════════════════════════════════════
# ORACLE AUTO-SEED FK PARENT TABLES
# ═══════════════════════════════════════════════════════════════════════

def auto_seed_fk_oracle(engine, target_table, ora_schema, stg_schema, stg_table,
                        col_mapping, source_file: str = "", references_dir: str = ""):
    """
    Auto-seed all FK parent tables for an Oracle target table using direct SQL.
    Gets distinct values from staging, checks existence, inserts missing rows.
    Returns list of (table, message) tuples.
    """
    from sqlalchemy import text as _t
    from collections import defaultdict
    import datetime as _dt

    results = []
    # Dispose connection pool to get fresh reads — avoids stale txn phantom rows
    try:
        engine.dispose()
    except Exception:
        pass

    q = lambda n: '"' + str(n).upper() + '"'
    stg_full  = q(stg_schema) + "." + q(stg_table)
    tgt_upper = target_table.upper()
    sch_upper = ora_schema.upper()

    AUDIT_COLS = {"PPDM_GUID","ROW_CREATED_BY","ROW_CREATED_DATE",
                  "ROW_CHANGED_BY","ROW_CHANGED_DATE",
                  "ROW_EFFECTIVE_DATE","ROW_EXPIRY_DATE","ACTIVE_IND","SOURCE"}

    def audit_val(col):
        col = col.upper()
        if col == "PPDM_GUID":      return ("RAWTOHEX(SYS_GUID())", None)
        if col == "ACTIVE_IND":     return (":_aind", "Y")
        if col == "SOURCE":         return (":_src", "PPDM_LOADER")
        if "EFFECTIVE" in col:      return ("TO_DATE('1900-01-01','YYYY-MM-DD')", None)
        if "EXPIRY" in col:         return ("TO_DATE('2099-12-31','YYYY-MM-DD')", None)
        if "DATE" in col:           return ("SYS_EXTRACT_UTC(SYSTIMESTAMP)", None)
        return (":_by", "PPDM_LOADER")

    # Build mapping: ppdm_col.upper() → (source_col.upper(), transform.upper())
    mapping_info = {}
    if col_mapping:
        for m in col_mapping.mapped:
            if m.source_col and not getattr(m, "auto_generated", False):
                mapping_info[m.ppdm_col.upper()] = (
                    m.source_col.upper(),
                    (getattr(m, "transform", "") or "").upper()
                )

    try:
        # Get all FK constraints on target table
        with engine.connect() as con:
            fk_rows = con.execute(_t(
                "SELECT cc.column_name, rcon.table_name, rcon.owner, pc.column_name "
                "FROM all_constraints con "
                "JOIN all_cons_columns cc "
                "  ON cc.constraint_name=con.constraint_name AND cc.owner=con.owner "
                "JOIN all_constraints rcon "
                "  ON rcon.constraint_name=con.r_constraint_name AND rcon.owner=con.r_owner "
                "JOIN all_cons_columns pc "
                "  ON pc.constraint_name=rcon.constraint_name AND pc.owner=rcon.owner "
                "  AND pc.position=cc.position "
                "WHERE con.constraint_type='R' "
                "  AND con.table_name=:tbl AND con.owner=:sch "
                "ORDER BY rcon.table_name, cc.position"
            ), {"tbl": tgt_upper, "sch": sch_upper}).fetchall()

        fk_by_parent = defaultdict(list)
        for child_col, parent_tbl, parent_sch, parent_pk in fk_rows:
            fk_by_parent[(parent_tbl.upper(), parent_sch.upper())].append(
                (child_col.upper(), parent_pk.upper())
            )

        for (parent_tbl, parent_sch), col_pairs in fk_by_parent.items():
            try:
                pfull = q(parent_sch) + "." + q(parent_tbl)

                # Note: no pre-check for existing rows — INSERT handles duplicates
                # via exception handler. Avoids stale connection pool false positives.

                # Find a mapped child FK column
                src_col = None
                transform = ""
                parent_pk = None
                for child_col, ppk in col_pairs:
                    if child_col in mapping_info:
                        src_col, transform = mapping_info[child_col]
                        parent_pk = ppk
                        break

                if not src_col:
                    continue  # no mapped source col — skip silently

                # Build Oracle SQL expression for the value.
                # REGEXP_REPLACE strips ALL whitespace (space, tab, CR, LF)
                # before hashing — TRIM() only strips spaces, leaving tabs
                # which produce a different SHA-1 and ORA-12899 (value too large).
                # Strip spaces, tabs (CHR(9)), CR (CHR(13)), LF (CHR(10))
                # Oracle POSIX regex does not reliably match \s in brackets
                _ws_strip = (
                    "REPLACE(REPLACE(REPLACE(REPLACE(" + q(src_col) + ","
                    "CHR(9),''),CHR(13),''),CHR(10),''),' ','')"
                )
                if transform == "SHA1":
                    val_expr = (
                        "UPPER(RAWTOHEX(DBMS_CRYPTO.HASH("
                        "UTL_RAW.CAST_TO_RAW(UPPER(TRIM(" + _ws_strip + "))),3)))"
                    )
                else:
                    val_expr = "UPPER(TRIM(" + _ws_strip + "))"

                # Get distinct values from staging
                with engine.connect() as con:
                    raw_vals = [r[0] for r in con.execute(_t(
                        "SELECT DISTINCT " + val_expr +
                        " FROM " + stg_full +
                        " WHERE TRIM(" + q(src_col) + ") IS NOT NULL"
                        " ORDER BY 1"
                    )).fetchall() if r[0]]

                if not raw_vals:
                    continue

                # Get parent table column metadata
                with engine.connect() as con:
                    parent_meta = {
                        r[0].upper(): {"type": r[1].upper(), "nullable": r[2] == "Y",
                                       "max_len": int(r[3]) if r[3] else 4000}
                        for r in con.execute(_t(
                            "SELECT column_name, data_type, nullable, char_length "
                            "FROM all_tab_columns "
                            "WHERE owner=:sch AND table_name=:tbl"
                        ), {"sch": parent_sch, "tbl": parent_tbl}).fetchall()
                    }

                # Get all PK columns (for compound PK)
                with engine.connect() as con:
                    pk_col_list = [r[0].upper() for r in con.execute(_t(
                        "SELECT cc.column_name FROM all_constraints con "
                        "JOIN all_cons_columns cc "
                        "  ON cc.constraint_name=con.constraint_name AND cc.owner=con.owner "
                        "WHERE con.constraint_type='P' "
                        "  AND con.table_name=:tbl AND con.owner=:sch "
                        "ORDER BY cc.position"
                    ), {"tbl": parent_tbl, "sch": parent_sch}).fetchall()]

                if not pk_col_list:
                    pk_col_list = [parent_pk]

                # Build INSERT statement
                tgt_cols  = []
                val_parts = []  # (placeholder_or_expr, param_key_or_None)

                # All PK cols get the seeded value (capped to max length)
                for pkc in pk_col_list:
                    meta = parent_meta.get(pkc, {})
                    maxlen = meta.get("max_len", 4000)
                    tgt_cols.append(q(pkc))
                    val_parts.append((":_pkv", None))  # placeholder — value set per row

                # Audit cols
                _audit_params = {}
                for acol in AUDIT_COLS:
                    if acol in parent_meta:
                        expr, fixed_val = audit_val(acol)
                        tgt_cols.append(q(acol))
                        val_parts.append((expr, fixed_val))
                        if fixed_val is not None:
                            _audit_params[expr[1:]] = fixed_val  # strip leading ':'

                ins_sql = (
                    "INSERT INTO " + pfull +
                    " (" + ", ".join(tgt_cols) + ") "
                    "VALUES (" + ", ".join(p for p, _ in val_parts) + ")"
                )

                # Existence check SQL
                pk_checks = " AND ".join(q(pkc) + "=:_pkv" for pkc in pk_col_list)
                chk_sql = "SELECT 1 FROM " + pfull + " WHERE " + pk_checks

                inserted = 0
                skipped  = 0
                for val in raw_vals:
                    # Cap value to pk col max length
                    meta0 = parent_meta.get(pk_col_list[0], {})
                    maxlen0 = meta0.get("max_len", 4000)
                    capped = val[:maxlen0] if val and maxlen0 < 4000 else val

                    params = {"_pkv": capped}
                    params.update(_audit_params)
                    try:
                        with engine.begin() as con:
                            con.execute(_t(ins_sql), params)
                        inserted += 1
                    except Exception:
                        # Duplicate or other error — skip silently
                        skipped += 1

                results.append((parent_tbl.lower(), f"seeded {inserted:,} rows ({skipped} skipped)"))

                # Write audit CSV
                if references_dir and inserted > 0:
                    try:
                        import csv as _csv, pathlib as _pl
                        _refs_path = _pl.Path(references_dir)
                        _refs_path.mkdir(parents=True, exist_ok=True)
                        _csv_path  = _refs_path / (parent_tbl.lower() + ".csv")
                        _seeded_at = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                        _write_hdr = not _csv_path.exists()
                        with open(_csv_path, "a", newline="", encoding="utf-8") as _cf:
                            _wr = _csv.writer(_cf)
                            if _write_hdr:
                                _wr.writerow(["ppdm_id","source_file","source_table","seeded_at"])
                            for v in raw_vals[:inserted]:
                                _wr.writerow([v, source_file, stg_table, _seeded_at])
                    except Exception:
                        pass

            except Exception as e:
                results.append((parent_tbl.lower(), f"skipped ({str(e)[:80]})"))

    except Exception as e:
        results.append(("error", str(e)[:120]))

    return results
