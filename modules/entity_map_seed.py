"""
entity_map_seed.py  —  DataView v3 · Table-driven entity parent seeder
======================================================================
Seeds entity parent tables (dv_business_associate, dv_field, ...) from the
staging table, driven entirely by a single mapping table:

    dataview.dv_entity_map(source_column, target_table, name_col)

Each row says "the staging column <source_column> supplies the name column
<name_col> of <target_table>". The primary key value is GENERATED as the
canonical SHA-1 of that name, so the parent row's PK equals the hashed FK
value promote computes into dv_well — they match by construction because
both use the IDENTICAL recipe and the IDENTICAL source column.

Recipe (must equal promote's child expression and hash_keys.entity_id):
    CONVERT(CHAR(40), HASHBYTES('SHA1', UPPER(LTRIM(RTRIM(<col>)))), 2)
HASHBYTES on the nvarchar staging column hashes UTF-16-LE; CONVERT(...,2)
emits uppercase hex — identical to the Python recipe in hash_keys.py.

Call this server-side just before the dv_well insert. Idempotent: every
insert is guarded by NOT EXISTS, so re-running a load seeds nothing new.
"""
from __future__ import annotations

from sqlalchemy import text

# Standard DataView audit columns we populate when the target table has them.
# (Only columns that actually exist on the target are included in the INSERT.)
_AUDIT_DEFAULTS = {
    "active_ind":       "'Y'",
    "source":           ":source",          # FK to dv_r_source — ensured first
    "row_created_by":   ":loader",
    "row_changed_by":   ":loader",
    "row_created_date": "GETDATE()",
    "row_changed_date": "GETDATE()",
}

# Placeholder/junk names that should NOT become entities. Matched case- and
# space-insensitively; such wells get a NULL FK at promote instead of pointing
# at a bogus parent. Extend as needed.
_IGNORE_NAMES = {
    "unavailable", "unknown", "wildcat", "n/a", "na",
    "none", "null", "tbd", "undesignated", "not available",
}


def _ignore_sql() -> str:
    vals = sorted(v for v in _IGNORE_NAMES if v)
    return ", ".join("'" + v.replace("'", "''") + "'" for v in vals)

# Canonical SHA-1 expression. {col} is a bracket-quoted column reference.
# MUST match mapping.build_transform_sql(..., "SHA1") exactly — including the
# CAST AS NVARCHAR(4000) — so the parent ba_id (seeded here) equals the child
# operator_ba_id (computed by promote's SHA1 transform), even if the staging
# column is VARCHAR.
def _hash_expr(col_ref: str) -> str:
    return (f"CONVERT(CHAR(40), HASHBYTES('SHA1', "
            f"CAST(UPPER(LTRIM(RTRIM({col_ref}))) AS NVARCHAR(4000))), 2)")


def _columns_of(con, schema: str, table: str) -> set[str]:
    rows = con.execute(text(
        "SELECT c.name FROM sys.columns c "
        "WHERE c.object_id = OBJECT_ID(:t)"), {"t": f"{schema}.{table}"}).fetchall()
    return {r[0].lower() for r in rows}


def _pk_column(con, schema: str, table: str) -> str | None:
    row = con.execute(text("""
        SELECT TOP 1 c.name
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c        ON c.object_id  = ic.object_id AND c.column_id  = ic.column_id
        WHERE i.is_primary_key = 1 AND i.object_id = OBJECT_ID(:t)
        ORDER BY ic.key_ordinal
    """), {"t": f"{schema}.{table}"}).fetchone()
    return row[0] if row else None


def _ensure_source_code(con, source: str, loader: str) -> None:
    """The entity tables' `source` column FKs to dv_r_source — make sure the
    code exists before we insert rows that reference it."""
    con.execute(text("""
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_source WHERE source = :s)
        INSERT INTO dataview.dv_r_source
            (source, short_name, long_name, active_ind,
             row_created_by, row_created_date, row_changed_by, row_changed_date)
        VALUES (:s, :s, :s, 'Y', :loader, GETDATE(), :loader, GETDATE())
    """), {"s": source, "loader": loader})


def seed_from_entity_map(
    engine,
    stg_schema: str,
    stg_table: str,
    target_schema: str = "dataview",
    source: str = "IMPORT",
    loader: str = "ENTITY_MAP",
) -> list[str]:
    """
    Seed every entity parent declared in dataview.dv_entity_map from the
    staging table. Returns a list of human-readable result lines.

    For each active map row whose source_column actually exists in staging:
      INSERT INTO <target_table> (<pk>, <name_col>, <audit...>)
      SELECT DISTINCT  hash(source_column), source_column, <audit values>
      FROM   <stg>.<stg_table>
      WHERE  source_column IS NOT NULL AND TRIM(source_column) <> ''
        AND  NOT EXISTS (parent row with that pk)
    """
    report: list[str] = []
    with engine.begin() as con:
        # Map table may not exist yet — fail soft so promote isn't blocked.
        if not con.execute(text(
                "SELECT OBJECT_ID('dataview.dv_entity_map')")).scalar():
            return ["dv_entity_map not found — skipped entity seeding"]

        _ensure_source_code(con, source, loader)

        stg_cols = _columns_of(con, stg_schema, stg_table)

        map_rows = con.execute(text("""
            SELECT source_column, target_table, name_col
            FROM dataview.dv_entity_map
            WHERE active_ind = 'Y'
        """)).fetchall()

        for src_col, tgt_table, name_col in map_rows:
            if src_col.lower() not in stg_cols:
                report.append(f"{tgt_table}: source column [{src_col}] "
                              f"not in staging — skipped")
                continue

            pk_col = _pk_column(con, target_schema, tgt_table)
            if not pk_col:
                report.append(f"{tgt_table}: no primary key found — skipped")
                continue

            tgt_cols = _columns_of(con, target_schema, tgt_table)
            audit = {c: expr for c, expr in _AUDIT_DEFAULTS.items()
                     if c in tgt_cols}

            insert_cols = [pk_col, name_col] + list(audit.keys())
            hexpr = _hash_expr(f"s.[{src_col}]")
            select_vals = [hexpr, f"s.[{src_col}]"] + list(audit.values())

            sql = (
                f"INSERT INTO [{target_schema}].[{tgt_table}] "
                f"({', '.join('[' + c + ']' for c in insert_cols)})\n"
                f"SELECT DISTINCT {', '.join(select_vals)}\n"
                f"FROM [{stg_schema}].[{stg_table}] s\n"
                f"WHERE s.[{src_col}] IS NOT NULL "
                f"AND LTRIM(RTRIM(s.[{src_col}])) <> ''\n"
                f"AND LOWER(LTRIM(RTRIM(s.[{src_col}]))) NOT IN ({_ignore_sql()})\n"
                f"AND NOT EXISTS (SELECT 1 FROM [{target_schema}].[{tgt_table}] t "
                f"WHERE t.[{pk_col}] = {_hash_expr('s.[' + src_col + ']')})"
            )
            res = con.execute(text(sql), {"source": source, "loader": loader})
            n = res.rowcount if res.rowcount is not None else -1
            report.append(f"{tgt_table}: seeded {n} new from [{src_col}] "
                          f"-> [{name_col}]")

    return report


def seed_source_values(col_mapping, engine, stg_schema, stg_table,
                       well_source_col: str = "source",
                       r_table: str = "dv_r_source", r_key: str = "source",
                       target_schema: str = "dataview",
                       loader: str = "ENTITY_MAP") -> list[str]:
    """
    Ensure every value destined for dv_well.<well_source_col> already exists in
    dv_r_source, so the dv_well -> dv_r_source FK resolves.

    Unlike the entity seed, these are pass-through (NOT hashed) values — e.g.
    DATA_SOURCE = 'CHEVRON'. We read the actual expression the mapping sends to
    the source column and seed dv_r_source from its DISTINCT staging values.
    Set-based, NOT EXISTS guarded, idempotent.
    """
    report: list[str] = []
    if col_mapping is None or not hasattr(col_mapping, "mapped"):
        return ["no col_mapping — skipped source seed"]

    m = next((m for m in col_mapping.mapped
              if (m.ppdm_col or "").lower() == well_source_col.lower()), None)
    if m is None:
        return [f"no mapping for [{well_source_col}] — skipped source seed"]

    expr = m.select_expr   # bare SQL scalar expr, e.g. [DATA_SOURCE] or 'CHEVRON'

    sql = f"""
        INSERT INTO {target_schema}.{r_table}
            ({r_key}, short_name, long_name, active_ind,
             row_created_by, row_created_date, row_changed_by, row_changed_date)
        SELECT DISTINCT s.v, LEFT(s.v, 40), s.v, 'Y',
               :loader, GETDATE(), :loader, GETDATE()
        FROM (SELECT DISTINCT {expr} AS v
              FROM {stg_schema}.{stg_table}) s
        WHERE s.v IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM {target_schema}.{r_table} r
                          WHERE r.{r_key} = s.v)
    """
    with engine.begin() as con:
        if not con.execute(text(
                f"SELECT OBJECT_ID('{target_schema}.{r_table}')")).scalar():
            return [f"{r_table} not found — skipped source seed"]
        res = con.execute(text(sql), {"loader": loader})
        n = res.rowcount if res.rowcount is not None else -1
    report.append(f"{r_table}: seeded {n} new from [{well_source_col}]")
    return report


def reconcile_entity_fk_mapping(col_mapping, engine, target_table,
                                target_schema: str = "dataview") -> list[str]:
    """
    Make the column mapping consistent with the live target table and the
    entity map, so promote builds a valid INSERT that writes hashed FK PKs.

    Two jobs:
      1. Drop any mapping whose target column does NOT exist on the live target
         table (phantom columns left by a stale schema JSON — e.g. operator_name).
         These would fail the INSERT with "Invalid column name".
      2. For every active dv_entity_map row, ensure the FK column (e.g.
         operator_ba_id) is mapped from its source column with transform="SHA1".
         One source may feed several FK columns (operator_ba_id AND
         original_operator_ba_id both from OPERATOR) — keyed on fk_column.

    Mutates col_mapping in place. Idempotent. Returns result lines.
    """
    report: list[str] = []
    if col_mapping is None or not hasattr(col_mapping, "mapped"):
        return ["no col_mapping — skipped FK reconcile"]

    with engine.begin() as con:
        if not con.execute(text(
                "SELECT OBJECT_ID('dataview.dv_entity_map')")).scalar():
            return ["dv_entity_map not found — skipped FK reconcile"]
        real_cols = {r[0].lower() for r in con.execute(text(
            "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(:t)"),
            {"t": f"{target_schema}.{target_table}"}).fetchall()}
        rows = con.execute(text(
            "SELECT source_column, fk_column FROM dataview.dv_entity_map "
            "WHERE active_ind = 'Y' AND fk_column IS NOT NULL")).fetchall()

    if not real_cols:
        return [f"target {target_schema}.{target_table} has no columns — skipped"]

    # 1. Drop phantom-target mappings (would otherwise error on INSERT).
    phantoms = [m.ppdm_col for m in col_mapping.mapped
                if (m.ppdm_col or "").lower() not in real_cols]
    if phantoms:
        col_mapping.mapped = [m for m in col_mapping.mapped
                              if (m.ppdm_col or "").lower() in real_cols]
        report.append("dropped phantom target(s): " + ", ".join(phantoms))

    # 2. Ensure each entity FK column is mapped from its source with SHA1.
    try:
        from modules.mapping import MappedColumn
    except Exception:
        MappedColumn = None

    by_ppdm = {(m.ppdm_col or "").lower(): m for m in col_mapping.mapped}
    for src_col, fk_col in rows:
        if fk_col.lower() not in real_cols:
            report.append(f"[{fk_col}] absent on {target_table} — skipped")
            continue
        m = by_ppdm.get(fk_col.lower())
        if m is not None:
            m.source_col = src_col
            m.transform  = "SHA1"
            report.append(f"[{src_col}] -> [{fk_col}] SHA1 (set)")
        elif MappedColumn is not None:
            nm = MappedColumn(ppdm_col=fk_col, source_col=src_col,
                              transform="SHA1")
            col_mapping.mapped.append(nm)
            by_ppdm[fk_col.lower()] = nm
            report.append(f"[{src_col}] -> [{fk_col}] SHA1 (added)")

    return report
