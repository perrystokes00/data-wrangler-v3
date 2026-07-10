"""
schema_cache.py
===============
Reflect ALL promote-relevant schema metadata in a handful of queries ONCE per
run, instead of re-querying the system catalogs per table.

Why: promote_table -> shared_columns / _reference_fk_predicates /
_computed_cols / _purge_children_by_inventory each hit sys.columns,
sys.foreign_keys, INFORMATION_SCHEMA.COLUMNS *per table*. Those system-view
joins are CPU-heavy, and the metadata is static — identical every run and
every table. On tiny data that reflection IS the runtime (~0.9 s/table on a
few hundred rows). Caching it once collapses ~150 catalog round-trips into ~4.

Usage in promote_catalog.py:
    import schema_cache as sc
    ...
    def run_promote(cur, ...):
        sc.prepare_schema(cur, DV_SCHEMA, CAT_SCHEMA)   # <-- add this line first
        ...

Then each helper consults the cache, falling back to a live query when the
cache wasn't primed (so standalone/ad-hoc calls still work). See the patch
notes shipped alongside this file.
"""
from __future__ import annotations

_READY = False
_COLS = {}        # (SCHEMA_UP, TABLE_UP) -> [col_name, ...]  (ordinal order)
_COMPUTED = {}    # TABLE_UP -> {COL_UP, ...}                  (dataview)
_REFFK = {}       # TABLE_UP -> [(local_col, ref_table, ref_col), ...] (dv_r_* FKs)
_CHILDREN = {}    # TABLE_UP -> [child_table, ...]             (dataview, excl self)
_TABLES = set()   # {(SCHEMA_UP, TABLE_UP), ...}
_HASINV = set()   # {TABLE_UP, ...}  dataview tables with an INVENTORY_ID column


def prepare_schema(cur, dv_schema: str, cat_schema: str):
    """Run the 4 reflection queries and fill the caches. Idempotent."""
    global _READY
    _COLS.clear(); _COMPUTED.clear(); _REFFK.clear()
    _CHILDREN.clear(); _TABLES.clear(); _HASINV.clear()

    # 1. every column of both schemas, in ordinal order
    cur.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA IN (?, ?) "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION",
        dv_schema, cat_schema)
    for sch, tbl, col in cur.fetchall():
        key = (sch.upper(), tbl.upper())
        _COLS.setdefault(key, []).append(col)
        _TABLES.add(key)
        if sch.upper() == dv_schema.upper() and col.upper() == "INVENTORY_ID":
            _HASINV.add(tbl.upper())

    # 2. computed columns (dataview) — promote can't INSERT into these
    cur.execute(
        "SELECT t.name, c.name FROM sys.columns c "
        "JOIN sys.tables t  ON t.object_id = c.object_id "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "WHERE s.name = ? AND c.is_computed = 1", dv_schema)
    for tbl, col in cur.fetchall():
        _COMPUTED.setdefault(tbl.upper(), set()).add(col.upper())

    # 3. reference-FK columns (dataview tables -> dv_r_* references)
    cur.execute(
        "SELECT pt.name, cpa.name, rt.name, cref.name "
        "FROM sys.foreign_keys fk "
        "JOIN sys.foreign_key_columns fkc "
        "       ON fkc.constraint_object_id = fk.object_id "
        "JOIN sys.tables  pt  ON pt.object_id = fk.parent_object_id "
        "JOIN sys.schemas ps  ON ps.schema_id = pt.schema_id "
        "JOIN sys.tables  rt  ON rt.object_id = fk.referenced_object_id "
        "JOIN sys.columns cpa ON cpa.object_id = fkc.parent_object_id "
        "                    AND cpa.column_id = fkc.parent_column_id "
        "JOIN sys.columns cref ON cref.object_id = fkc.referenced_object_id "
        "                     AND cref.column_id = fkc.referenced_column_id "
        "WHERE ps.name = ? AND rt.name LIKE 'dv[_]r[_]%'", dv_schema)
    for parent, local_col, ref_table, ref_col in cur.fetchall():
        _REFFK.setdefault(parent.upper(), []).append(
            (local_col, ref_table, ref_col))

    # 4. FK children within dataview (who points AT whom), excluding self-refs
    cur.execute(
        "SELECT OBJECT_NAME(fk.referenced_object_id), "
        "       OBJECT_NAME(fk.parent_object_id) "
        "FROM sys.foreign_keys fk "
        "JOIN sys.tables  rt ON rt.object_id = fk.referenced_object_id "
        "JOIN sys.schemas s  ON s.schema_id = rt.schema_id "
        "WHERE s.name = ? AND fk.parent_object_id <> fk.referenced_object_id",
        dv_schema)
    for parent, child in cur.fetchall():
        if parent and child:
            lst = _CHILDREN.setdefault(parent.upper(), [])
            if child not in lst:
                lst.append(child)

    _READY = True
    return {"tables": len(_TABLES), "ref_fk_tables": len(_REFFK),
            "child_parents": len(_CHILDREN), "computed_tables": len(_COMPUTED)}


# ── accessors (return None / empty on miss so callers can fall back live) ────
def ready() -> bool:
    return _READY


def reset():
    global _READY
    _READY = False


def table_exists(schema: str, table: str) -> bool:
    return (schema.upper(), table.split('.')[-1].upper()) in _TABLES


def cols_of(schema: str, table: str):
    return _COLS.get((schema.upper(), table.split('.')[-1].upper()))


def computed_of(table: str):
    return _COMPUTED.get(table.split('.')[-1].upper(), set())


def ref_fks_of(table: str):
    return _REFFK.get(table.split('.')[-1].upper(), [])


def children_of(table: str):
    return list(_CHILDREN.get(table.split('.')[-1].upper(), []))


def has_inventory(table: str) -> bool:
    return table.split('.')[-1].upper() in _HASINV
