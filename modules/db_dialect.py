"""
db_dialect.py  —  Data Wrangler · Database Dialect Abstraction
==============================================================
Provides a thin dialect layer so the pipeline never writes
raw SQL directly. Each engine subclass returns the correct
SQL expressions and statements for its platform.

Currently implemented:
    SQLServerDialect  — T-SQL / SQL Server 2016+

Adding a new engine:
    1. Subclass DBDialect
    2. Override every abstract method
    3. Register in DIALECTS dict at the bottom
    4. Add the engine name to the connect UI

Performance overhead: zero — methods return strings, no DB
calls are made here. All execution cost is in the caller.

Usage:
    from modules.db_dialect import get_dialect
    dialect = get_dialect("sqlserver")
    sql = dialect.normalize_sql("stg", "raw_data", col_list, col_types)
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# ABSTRACT BASE
# ═══════════════════════════════════════════════════════════════════════

class DBDialect(ABC):
    """
    Abstract dialect interface.  Every method returns a SQL string (or list
    of strings) ready to execute against the target engine.  No DB connections
    are opened here — the caller owns the connection.
    """

    # ── Identity ──────────────────────────────────────────────────────
    @property
    @abstractmethod
    def name(self) -> str:
        """Short engine name, e.g. 'sqlserver', 'oracle', 'snowflake'."""

    @property
    @abstractmethod
    def placeholder(self) -> str:
        """Parameter placeholder style: ':name' (most), '%(name)s' (psycopg2)."""

    # ── Schema introspection ──────────────────────────────────────────
    @abstractmethod
    def introspect_columns_sql(self, schema: str, table: str) -> str:
        """
        Returns a SELECT that yields one row per column with fields:
            name, type_name, is_nullable (bool), is_identity (bool),
            is_pk (bool), is_computed (bool), max_length (int)
        """

    @abstractmethod
    def introspect_fks_sql(self, schema: str, table: str) -> str:
        """
        Returns a SELECT that yields one row per FK column with fields:
            child_col, parent_table, parent_col
        """

    @abstractmethod
    def introspect_tables_sql(self, schema: str) -> str:
        """Returns a SELECT that yields table names in schema, ordered."""

    @abstractmethod
    def row_count_sql(self, schema: str, table: str) -> str:
        """Fast approximate or exact row count query."""

    # ── Bulk load ─────────────────────────────────────────────────────
    @abstractmethod
    def bulk_load_sql(
        self,
        file_path: str,
        schema: str,
        table: str,
        delimiter: str = ",",
        has_header: bool = True,
        encoding: str = "UTF-8",
    ) -> str:
        """Returns the statement that loads a flat file into a staging table."""

    # ── Normalization expressions ─────────────────────────────────────
    @abstractmethod
    def trim_expr(self, col: str) -> str:
        """Expression that trims whitespace, removes CR/LF, and nullifies empty."""

    @abstractmethod
    def upper_expr(self, col: str) -> str:
        """UPPER() expression."""

    @abstractmethod
    def try_convert_date_expr(self, col: str) -> str:
        """
        Expression that tries to parse a string column as a date using common
        formats, returning ISO YYYY-MM-DD string or NULL on failure.
        """

    @abstractmethod
    def normalize_sql(
        self,
        schema: str,
        table: str,
        col_list: list[str],
        col_types: dict[str, str],
    ) -> list[str]:
        """
        Returns list of UPDATE statements that apply trim/upper/date
        normalization in a single round trip where possible.
        """

    # ── Server-generated value expressions ───────────────────────────
    @abstractmethod
    def guid_expr(self) -> str:
        """Expression that generates a new UUID/GUID."""

    @abstractmethod
    def current_utc_expr(self) -> str:
        """Expression for current UTC timestamp."""

    @abstractmethod
    def effective_date_expr(self) -> str:
        """Default effective date expression ('beginning of time')."""

    @abstractmethod
    def expiry_date_expr(self) -> str:
        """Default expiry date expression ('end of time')."""

    # ── Promote (INSERT / MERGE) ──────────────────────────────────────
    @abstractmethod
    def insert_select_sql(
        self,
        src_schema: str,
        src_table: str,
        tgt_schema: str,
        tgt_table: str,
        col_pairs: list[tuple[str, str]],   # [(target_col, src_expr), ...]
        pk_cols: list[str],
    ) -> str:
        """INSERT INTO target SELECT … FROM staging WHERE NOT EXISTS (dupe PK)."""

    @abstractmethod
    def merge_sql(
        self,
        src_schema: str,
        src_table: str,
        tgt_schema: str,
        tgt_table: str,
        col_pairs: list[tuple[str, str]],
        pk_cols: list[str],
    ) -> str:
        """MERGE (upsert) statement keyed on pk_cols."""

    # ── Helpers exposed to callers ────────────────────────────────────
    def quote(self, name: str) -> str:
        """Wrap an identifier in the engine's quoting style."""
        return self._quote(name)

    @abstractmethod
    def _quote(self, name: str) -> str: ...

    def qualified(self, schema: str, table: str) -> str:
        return f"{self._quote(schema)}.{self._quote(table)}"


# ═══════════════════════════════════════════════════════════════════════
# SQL SERVER IMPLEMENTATION
# ═══════════════════════════════════════════════════════════════════════

class SQLServerDialect(DBDialect):
    """
    T-SQL dialect for SQL Server 2016+.
    Mirrors the SQL that was previously scattered across normalize.py,
    staging.py, promote.py, and the RTM/FK introspection blocks in app.py.
    """

    @property
    def name(self) -> str:
        return "sqlserver"

    @property
    def placeholder(self) -> str:
        return ":name"   # SQLAlchemy named params

    # ── Identifier quoting ────────────────────────────────────────────
    def _quote(self, name: str) -> str:
        return f"[{name}]"

    # ── Schema introspection ──────────────────────────────────────────
    def introspect_columns_sql(self, schema: str, table: str) -> str:
        return """
            SELECT
                c.name                                        AS name,
                tp.name                                       AS type_name,
                CAST(c.is_nullable  AS bit)                   AS is_nullable,
                CAST(c.is_identity  AS bit)                   AS is_identity,
                CAST(CASE WHEN ic.column_id IS NOT NULL
                          THEN 1 ELSE 0 END AS bit)           AS is_pk,
                CAST(c.is_computed  AS bit)                   AS is_computed,
                c.max_length                                  AS max_length
            FROM sys.columns c
            JOIN sys.types   tp ON tp.user_type_id = c.user_type_id
            JOIN sys.tables  t  ON t.object_id     = c.object_id
            JOIN sys.schemas s  ON s.schema_id     = t.schema_id
            LEFT JOIN sys.indexes i
                   ON i.object_id = c.object_id AND i.is_primary_key = 1
            LEFT JOIN sys.index_columns ic
                   ON ic.object_id  = c.object_id
                  AND ic.index_id   = i.index_id
                  AND ic.column_id  = c.column_id
            WHERE LOWER(t.name) = LOWER(:tbl)
              AND s.name = :sch
            ORDER BY c.column_id
        """

    def introspect_fks_sql(self, schema: str, table: str) -> str:
        return """
            SELECT
                cc.name  AS child_col,
                pt.name  AS parent_table,
                pc.name  AS parent_col
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc
                   ON fkc.constraint_object_id = fk.object_id
            JOIN sys.tables  ct  ON ct.object_id  = fk.parent_object_id
            JOIN sys.columns cc  ON cc.object_id  = fk.parent_object_id
                                AND cc.column_id  = fkc.parent_column_id
            JOIN sys.tables  pt  ON pt.object_id  = fk.referenced_object_id
            JOIN sys.columns pc  ON pc.object_id  = fk.referenced_object_id
                                AND pc.column_id  = fkc.referenced_column_id
            JOIN sys.schemas s   ON s.schema_id   = ct.schema_id
            WHERE LOWER(ct.name) = LOWER(:tbl)
              AND s.name = :sch
        """

    def introspect_tables_sql(self, schema: str) -> str:
        return """
            SELECT t.name
            FROM sys.tables  t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = :sch
            ORDER BY t.name
        """

    def row_count_sql(self, schema: str, table: str) -> str:
        # Fast stats-based count — accurate enough for display
        return f"""
            SELECT SUM(p.rows)
            FROM sys.partitions p
            JOIN sys.tables  t ON t.object_id  = p.object_id
            JOIN sys.schemas s ON s.schema_id  = t.schema_id
            WHERE p.index_id IN (0, 1)
              AND LOWER(t.name) = LOWER('{table}')
              AND s.name = '{schema}'
        """

    # ── Bulk load ─────────────────────────────────────────────────────
    def bulk_load_sql(
        self,
        file_path: str,
        schema: str,
        table: str,
        delimiter: str = ",",
        has_header: bool = True,
        encoding: str = "UTF-8",
    ) -> str:
        first_row = 2 if has_header else 1
        code_page = "65001" if encoding.upper() in ("UTF-8", "UTF8") else "ACP"
        return (
            f"BULK INSERT {self.qualified(schema, table)}\n"
            f"FROM '{file_path}'\n"
            f"WITH (\n"
            f"    FIELDTERMINATOR = '{delimiter}',\n"
            f"    ROWTERMINATOR   = '0x0a',\n"
            f"    FIRSTROW        = {first_row},\n"
            f"    CODEPAGE        = '{code_page}',\n"
            f"    TABLOCK\n"
            f")"
        )

    # ── Normalization expressions ─────────────────────────────────────
    def trim_expr(self, col: str) -> str:
        c = self._quote(col)
        return (
            f"NULLIF(LTRIM(RTRIM("
            f"REPLACE(REPLACE({c}, CHAR(13), ''), CHAR(10), '')"
            f")), '')"
        )

    def upper_expr(self, col: str) -> str:
        return f"UPPER({self._quote(col)})"

    def try_convert_date_expr(self, col: str) -> str:
        c = self._quote(col)
        coalesce = (
            f"COALESCE("
            f"TRY_CONVERT(date,{c},101),"   # MM/DD/YYYY  US slash
            f"TRY_CONVERT(date,{c},103),"   # DD/MM/YYYY  UK slash
            f"TRY_CONVERT(date,{c},105),"   # DD-MM-YYYY  EU dash
            f"TRY_CONVERT(date,{c},120)"    # YYYY-MM-DD  ISO
            f")"
        )
        return (
            f"CASE WHEN {c} IS NOT NULL AND {coalesce} IS NOT NULL "
            f"THEN CONVERT(varchar(10), {coalesce}, 23) "
            f"ELSE {c} END"
        )

    def normalize_sql(
        self,
        schema: str,
        table: str,
        col_list: list[str],
        col_types: dict[str, str],
    ) -> list[str]:
        """
        Single UPDATE covering trim + upper + date in one pass.
        Columns get the most specific transform that applies:
            date cols  → trim then date-convert
            code cols  → trim then UPPER
            string cols → trim only
        """
        from modules.normalize import (
            _is_indicator_col, _is_code_col,
            _is_date_col, _sql_type_hint,
        )

        full = self.qualified(schema, table)
        _SKIP = {"_batch_loaded_at"}
        set_clauses = []

        for col in col_list:
            if col in _SKIP:
                continue
            dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
            hint  = _sql_type_hint(dtype)

            in_trim  = (hint == "string")
            in_upper = (_is_indicator_col(col) or _is_code_col(col, dtype))
            in_date  = (hint in ("date", "datetime") or _is_date_col(col, []))

            if not (in_trim or in_upper or in_date):
                continue

            expr = self.trim_expr(col) if in_trim else self._quote(col)
            if in_upper:
                expr = f"UPPER({expr})"
            if in_date:
                c = self._quote(col)
                coalesce = (
                    f"COALESCE("
                    f"TRY_CONVERT(date,{expr},101),"
                    f"TRY_CONVERT(date,{expr},103),"
                    f"TRY_CONVERT(date,{expr},105),"
                    f"TRY_CONVERT(date,{expr},120)"
                    f")"
                )
                expr = (
                    f"CASE WHEN {c} IS NOT NULL AND {coalesce} IS NOT NULL "
                    f"THEN CONVERT(varchar(10),{coalesce},23) "
                    f"ELSE {expr} END"
                )

            set_clauses.append(f"{self._quote(col)} = {expr}")

        if not set_clauses:
            return []
        return [f"UPDATE {full} SET {', '.join(set_clauses)}"]

    # ── Server-generated value expressions ───────────────────────────
    def guid_expr(self) -> str:
        return "NEWID()"

    def current_utc_expr(self) -> str:
        return "GETUTCDATE()"

    def effective_date_expr(self) -> str:
        return "CAST('1900-01-01' AS DATETIME2)"

    def expiry_date_expr(self) -> str:
        return "CAST('2099-12-31' AS DATETIME2)"

    # ── Promote ───────────────────────────────────────────────────────
    def insert_select_sql(
        self,
        src_schema: str,
        src_table: str,
        tgt_schema: str,
        tgt_table: str,
        col_pairs: list[tuple[str, str]],
        pk_cols: list[str],
    ) -> str:
        tgt  = self.qualified(tgt_schema, tgt_table)
        src  = self.qualified(src_schema, src_table)
        tgt_cols = ", ".join(self._quote(c) for c, _ in col_pairs)
        src_expr = ", ".join(expr for _, expr in col_pairs)
        pk_join  = " AND ".join(
            f"tgt.{self._quote(p)} = src.{self._quote(p)}"
            for p in pk_cols
        )
        return (
            f"INSERT INTO {tgt} ({tgt_cols})\n"
            f"SELECT {src_expr}\n"
            f"FROM {src} src\n"
            f"WHERE NOT EXISTS (\n"
            f"    SELECT 1 FROM {tgt} tgt WHERE {pk_join}\n"
            f")"
        )

    def merge_sql(
        self,
        src_schema: str,
        src_table: str,
        tgt_schema: str,
        tgt_table: str,
        col_pairs: list[tuple[str, str]],
        pk_cols: list[str],
    ) -> str:
        tgt     = self.qualified(tgt_schema, tgt_table)
        src     = self.qualified(src_schema, src_table)
        pk_set  = {p.upper() for p in pk_cols}
        on_cls  = " AND ".join(
            f"tgt.{self._quote(p)} = src.{self._quote(p)}"
            for p in pk_cols
        )
        upd_pairs = [(c, e) for c, e in col_pairs if c.upper() not in pk_set]
        upd_cls   = ",\n        ".join(
            f"tgt.{self._quote(c)} = {e}" for c, e in upd_pairs
        )
        tgt_cols  = ", ".join(self._quote(c) for c, _ in col_pairs)
        src_exprs = ", ".join(e for _, e in col_pairs)
        return (
            f"MERGE {tgt} AS tgt\n"
            f"USING (\n"
            f"    SELECT {src_exprs} FROM {src}\n"
            f") AS src\n"
            f"ON ({on_cls})\n"
            f"WHEN MATCHED THEN UPDATE SET\n"
            f"    {upd_cls}\n"
            f"WHEN NOT MATCHED THEN\n"
            f"    INSERT ({tgt_cols})\n"
            f"    VALUES ({src_exprs});"
        )

    def current_schema_sql(self) -> str:
        return "SELECT SCHEMA_NAME()"

    def drop_table_if_exists_sql(self, schema: str, table: str) -> str:
        fq = self.qualified(schema, table)
        return f"IF OBJECT_ID('{schema}.{table}','U') IS NOT NULL DROP TABLE {fq}"

    def audit_exprs(self, row_source: str = "PPDM_LOADER") -> dict[str, str]:
        return {
            "ROW_CREATED_DATE":   self.current_utc_expr(),
            "ROW_CHANGED_DATE":   self.current_utc_expr(),
            "ROW_EFFECTIVE_DATE": self.effective_date_expr(),
            "ROW_EXPIRY_DATE":    self.expiry_date_expr(),
            "PPDM_GUID":          self.guid_expr(),
            "ACTIVE_IND":         "'Y'",
            "ROW_CREATED_BY":     f"'{row_source}'",
            "ROW_CHANGED_BY":     f"'{row_source}'",
        }





# ═══════════════════════════════════════════════════════════════════════
# ORACLE DIALECT
# ═══════════════════════════════════════════════════════════════════════

class OracleDialect(DBDialect):
    """
    Oracle 19c+ dialect (pure oracledb driver, no Instant Client).
    All catalog queries use ALL_* views — works with any connected user.
    Identifier quoting: double-quote + uppercase (Oracle standard).
    """

    @property
    def name(self) -> str:
        return "oracle"

    @property
    def placeholder(self) -> str:
        return ":name"   # SQLAlchemy / oracledb named params

    # ── Identifier quoting ────────────────────────────────────────────
    def _quote(self, name: str) -> str:
        return f'"{name.upper()}"'

    # ── Schema introspection ──────────────────────────────────────────
    def introspect_columns_sql(self, schema: str, table: str) -> str:
        return """
            SELECT
                c.column_name                                       AS name,
                c.data_type                                         AS type_name,
                CASE WHEN c.nullable = 'Y' THEN 1 ELSE 0 END         AS is_nullable,
                0                                                   AS is_identity,
                CASE WHEN p.column_name IS NOT NULL THEN 1 ELSE 0 END AS is_pk,
                0                                                   AS is_computed,
                c.char_length                                       AS max_length
            FROM all_tab_columns c
            LEFT JOIN (
                SELECT cc.column_name
                FROM all_constraints con
                JOIN all_cons_columns cc
                  ON cc.constraint_name = con.constraint_name
                 AND cc.owner           = con.owner
                WHERE con.constraint_type = 'P'
                  AND con.table_name = UPPER(:tbl)
                  AND con.owner      = UPPER(:sch)
            ) p ON p.column_name = c.column_name
            WHERE c.table_name = UPPER(:tbl)
              AND c.owner      = UPPER(:sch)
            ORDER BY c.column_id
        """

    def introspect_fks_sql(self, schema: str, table: str) -> str:
        return """
            SELECT
                cc.column_name  AS child_col,
                rcon.table_name AS parent_table,
                pc.column_name  AS parent_col
            FROM all_constraints con
            JOIN all_cons_columns cc
              ON cc.constraint_name = con.constraint_name
             AND cc.owner           = con.owner
            JOIN all_constraints rcon
              ON rcon.constraint_name = con.r_constraint_name
             AND rcon.owner           = con.r_owner
            JOIN all_cons_columns pc
              ON pc.constraint_name = rcon.constraint_name
             AND pc.owner           = rcon.owner
             AND pc.position        = cc.position
            WHERE con.constraint_type = 'R'
              AND con.table_name = UPPER(:tbl)
              AND con.owner      = UPPER(:sch)
        """

    def introspect_tables_sql(self, schema: str) -> str:
        return """
            SELECT table_name
            FROM all_tables
            WHERE owner = UPPER(:sch)
            ORDER BY table_name
        """

    def row_count_sql(self, schema: str, table: str) -> str:
        # COUNT(*) — ALL_TABLES.num_rows is stale until DBMS_STATS runs
        return f'SELECT COUNT(*) FROM "{schema.upper()}"."{table.upper()}"'

    # ── Bulk load ─────────────────────────────────────────────────────
    def bulk_load_sql(
        self,
        file_path: str,
        schema: str,
        table: str,
        delimiter: str = ",",
        has_header: bool = True,
        encoding: str = "UTF-8",
    ) -> str:
        # Oracle does not support server-side CSV load via SQL.
        # Actual loading is done via executemany in staging.py.
        # This placeholder is kept for interface compliance.
        return ""

    # ── Normalization expressions ─────────────────────────────────────
    def trim_expr(self, col: str) -> str:
        c = self._quote(col)
        return (
            f"NULLIF(TRIM(REPLACE(REPLACE({c}, CHR(13), ''), CHR(10), '')), '')"
        )

    def upper_expr(self, col: str) -> str:
        return f"UPPER({self._quote(col)})"

    def try_convert_date_expr(self, col: str) -> str:
        c = self._quote(col)
        # Try common formats; wrap in CASE to leave unparseable values alone
        return (
            f"CASE WHEN {c} IS NOT NULL AND TRIM({c}) != '' THEN "
            f"TO_CHAR("
            f"COALESCE("
            f"TO_DATE(TRIM({c}), 'YYYY-MM-DD'),"
            f"TO_DATE(TRIM({c}), 'MM/DD/YYYY'),"
            f"TO_DATE(TRIM({c}), 'DD-MM-YYYY')"
            f"), 'YYYY-MM-DD') "
            f"ELSE {c} END"
        )

    def normalize_sql(
        self,
        schema: str,
        table: str,
        col_list: list[str],
        col_types: dict[str, str],
    ) -> list[str]:
        """
        Oracle: UPDATE in-place in batches of 50 SET clauses.
        No SELECT INTO / temp table approach — Oracle doesn't support it.
        """
        from modules.normalize import (
            _is_indicator_col, _is_code_col,
            _is_date_col, _sql_type_hint,
        )

        full   = self.qualified(schema, table)
        _SKIP  = {"_batch_loaded_at", "_BATCH_LOADED_AT"}
        set_clauses = []

        for col in col_list:
            if col in _SKIP or col.upper() in _SKIP:
                continue
            dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
            hint  = _sql_type_hint(dtype)

            in_trim  = (hint == "string")
            in_upper = (_is_indicator_col(col) or _is_code_col(col, dtype))
            in_date  = (hint in ("date", "datetime") or _is_date_col(col, []))

            if not (in_trim or in_upper or in_date):
                continue

            expr = self.trim_expr(col) if in_trim else self._quote(col)
            if in_upper:
                expr = f"UPPER({expr})"
            if in_date:
                c = self._quote(col)
                expr = (
                    f"CASE WHEN {c} IS NOT NULL AND TRIM({c}) != '' THEN "
                    f"TO_CHAR(COALESCE("
                    f"TO_DATE(TRIM({c}),'YYYY-MM-DD'),"
                    f"TO_DATE(TRIM({c}),'MM/DD/YYYY'),"
                    f"TO_DATE(TRIM({c}),'DD-MM-YYYY')"
                    f"),'YYYY-MM-DD') ELSE {c} END"
                )

            set_clauses.append(f"{self._quote(col)} = {expr}")

        if not set_clauses:
            return []

        # Batch into groups of 50 to avoid ORA-24344
        BATCH = 50
        stmts = []
        for i in range(0, len(set_clauses), BATCH):
            batch = set_clauses[i:i + BATCH]
            stmts.append(f"UPDATE {full} SET {', '.join(batch)}")
        return stmts

    # ── Server-generated value expressions ───────────────────────────
    def guid_expr(self) -> str:
        return "RAWTOHEX(SYS_GUID())"

    def current_utc_expr(self) -> str:
        return "SYS_EXTRACT_UTC(SYSTIMESTAMP)"

    def effective_date_expr(self) -> str:
        return "TO_DATE('1900-01-01', 'YYYY-MM-DD')"

    def expiry_date_expr(self) -> str:
        return "TO_DATE('2099-12-31', 'YYYY-MM-DD')"

    # ── Current schema ────────────────────────────────────────────────
    def current_schema_sql(self) -> str:
        return "SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM dual"

    # ── Drop table if exists ──────────────────────────────────────────
    def drop_table_if_exists_sql(self, schema: str, table: str) -> str:
        fq = f'"{schema.upper()}"."{table.upper()}"'
        return (
            f"BEGIN "
            f"EXECUTE IMMEDIATE 'DROP TABLE {fq}'; "
            f"EXCEPTION WHEN OTHERS THEN "
            f"IF SQLCODE != -942 THEN RAISE; END IF; "
            f"END;"
        )

    # ── Promote ───────────────────────────────────────────────────────
    def insert_select_sql(
        self,
        src_schema: str,
        src_table: str,
        tgt_schema: str,
        tgt_table: str,
        col_pairs: list[tuple[str, str]],
        pk_cols: list[str],
    ) -> str:
        tgt      = self.qualified(tgt_schema, tgt_table)
        src      = self.qualified(src_schema, src_table)
        tgt_cols = ", ".join(self._quote(c) for c, _ in col_pairs)
        src_expr = ", ".join(expr for _, expr in col_pairs)
        pk_join  = " AND ".join(
            f"tgt.{self._quote(p)} = src.{self._quote(p)}"
            for p in pk_cols
        )
        return (
            f"INSERT INTO {tgt} ({tgt_cols})\n"
            f"SELECT {src_expr}\n"
            f"FROM {src} src\n"
            f"WHERE NOT EXISTS (\n"
            f"    SELECT 1 FROM {tgt} tgt WHERE {pk_join}\n"
            f")"
        )

    def merge_sql(
        self,
        src_schema: str,
        src_table: str,
        tgt_schema: str,
        tgt_table: str,
        col_pairs: list[tuple[str, str]],
        pk_cols: list[str],
    ) -> str:
        tgt      = self.qualified(tgt_schema, tgt_table)
        src      = self.qualified(src_schema, src_table)
        pk_set   = {p.upper() for p in pk_cols}
        on_cls   = " AND ".join(
            f"tgt.{self._quote(p)} = src.{self._quote(p)}"
            for p in pk_cols
        )
        upd_pairs = [(c, e) for c, e in col_pairs if c.upper() not in pk_set]
        upd_cls   = ",\n        ".join(
            f"tgt.{self._quote(c)} = {e}" for c, e in upd_pairs
        )
        tgt_cols  = ", ".join(self._quote(c) for c, _ in col_pairs)
        src_exprs = ", ".join(e for _, e in col_pairs)
        # Oracle MERGE has no trailing semicolon inside executemany context
        return (
            f"MERGE INTO {tgt} tgt\n"
            f"USING (\n"
            f"    SELECT {src_exprs} FROM {src}\n"
            f") src\n"
            f"ON ({on_cls})\n"
            f"WHEN MATCHED THEN UPDATE SET\n"
            f"    {upd_cls}\n"
            f"WHEN NOT MATCHED THEN\n"
            f"    INSERT ({tgt_cols})\n"
            f"    VALUES ({src_exprs})"
        )

    # ── Audit expressions convenience dict ───────────────────────────
    def audit_exprs(self, row_source: str = "PPDM_LOADER") -> dict[str, str]:
        return {
            "ROW_CREATED_DATE":   self.current_utc_expr(),
            "ROW_CHANGED_DATE":   self.current_utc_expr(),
            "ROW_EFFECTIVE_DATE": self.effective_date_expr(),
            "ROW_EXPIRY_DATE":    self.expiry_date_expr(),
            "PPDM_GUID":          self.guid_expr(),
            "ACTIVE_IND":         "'Y'",
            "ROW_CREATED_BY":     f"'{row_source}'",
            "ROW_CHANGED_BY":     f"'{row_source}'",
        }



# ═══════════════════════════════════════════════════════════════════════
# SNOWFLAKE DIALECT
# ═══════════════════════════════════════════════════════════════════════

class SnowflakeDialect(DBDialect):
    """
    Snowflake dialect.
    - Identifiers: double-quoted uppercase
    - FKs defined but not enforced
    - SHA1 via SHA1_HEX() not DBMS_CRYPTO
    - No LOG ERRORS support
    """

    @property
    def name(self) -> str:
        return "snowflake"

    @property
    def placeholder(self) -> str:
        return ":name"

    def _quote(self, name: str) -> str:
        return f'"{name.upper()}"'

    def introspect_columns_sql(self, schema: str, table: str) -> str:
        return """
            SELECT
                c.COLUMN_NAME                                        AS name,
                c.DATA_TYPE                                          AS type_name,
                CASE WHEN c.IS_NULLABLE = 'YES' THEN 1 ELSE 0 END   AS is_nullable,
                0                                                    AS is_identity,
                CASE WHEN k.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS is_pk,
                0                                                    AS is_computed,
                c.CHARACTER_MAXIMUM_LENGTH                           AS max_length
            FROM INFORMATION_SCHEMA.COLUMNS c
            LEFT JOIN (
                SELECT ku.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                  ON ku.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                 AND ku.TABLE_SCHEMA    = tc.TABLE_SCHEMA
                 AND ku.TABLE_NAME      = tc.TABLE_NAME
                WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                  AND tc.TABLE_SCHEMA = UPPER(:sch)
                  AND tc.TABLE_NAME   = UPPER(:tbl)
            ) k ON k.COLUMN_NAME = c.COLUMN_NAME
            WHERE c.TABLE_SCHEMA = UPPER(:sch)
              AND c.TABLE_NAME   = UPPER(:tbl)
            ORDER BY c.ORDINAL_POSITION
        """

    def introspect_fks_sql(self, schema: str, table: str) -> str:
        return """
            SELECT
                ku.COLUMN_NAME   AS child_col,
                rku.TABLE_NAME   AS parent_table,
                rku.COLUMN_NAME  AS parent_col
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
              ON ku.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
             AND ku.TABLE_SCHEMA    = rc.CONSTRAINT_SCHEMA
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE rku
              ON rku.CONSTRAINT_NAME  = rc.UNIQUE_CONSTRAINT_NAME
             AND rku.TABLE_SCHEMA     = rc.UNIQUE_CONSTRAINT_SCHEMA
             AND rku.ORDINAL_POSITION = ku.POSITION_IN_UNIQUE_CONSTRAINT
            WHERE ku.TABLE_SCHEMA = UPPER(:sch)
              AND ku.TABLE_NAME   = UPPER(:tbl)
        """

    def introspect_tables_sql(self, schema: str) -> str:
        return """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = UPPER(:sch)
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """

    def row_count_sql(self, schema: str, table: str) -> str:
        return f'SELECT COUNT(*) FROM "{schema.upper()}"."{table.upper()}"'

    def bulk_load_sql(self, file_path, schema, table,
                      delimiter=",", has_header=True, encoding="UTF-8") -> str:
        return ""  # Loading done via executemany in staging.py

    def trim_expr(self, col: str) -> str:
        c = self._quote(col)
        return f"NULLIF(TRIM({c}), '')"

    def upper_expr(self, col: str) -> str:
        return f"UPPER({self._quote(col)})"

    def try_convert_date_expr(self, col: str) -> str:
        c = self._quote(col)
        return (
            f"CASE WHEN {c} IS NOT NULL AND TRIM({c}) != '' THEN "
            f"TRY_TO_DATE(TRIM({c})) ELSE {c} END"
        )

    def normalize_sql(self, schema, table, col_list, col_types) -> list:
        from modules.normalize import (
            _is_indicator_col, _is_code_col, _is_date_col, _sql_type_hint)
        full = self.qualified(schema, table)
        _SKIP = {"_batch_loaded_at", "_BATCH_LOADED_AT"}
        set_clauses = []
        for col in col_list:
            if col in _SKIP or col.upper() in _SKIP:
                continue
            dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
            hint  = _sql_type_hint(dtype)
            in_trim  = (hint == "string")
            in_upper = (_is_indicator_col(col) or _is_code_col(col, dtype))
            in_date  = (hint in ("date", "datetime") or _is_date_col(col, []))
            if not (in_trim or in_upper or in_date):
                continue
            c = self._quote(col)
            if in_date:
                expr = (f"CASE WHEN {c} IS NOT NULL AND TRIM({c}) != '' "
                        f"THEN TRY_TO_DATE(TRIM({c})) ELSE {c} END")
            elif in_trim:
                expr = self.trim_expr(col)
                if in_upper:
                    expr = f"UPPER({expr})"
            else:
                expr = f"UPPER({c})"
            set_clauses.append(f"{c} = {expr}")
        if not set_clauses:
            return []
        BATCH = 100
        return [
            f"UPDATE {full} SET {chr(44).join(set_clauses[i:i+BATCH])}"
            for i in range(0, len(set_clauses), BATCH)
        ]

    def guid_expr(self) -> str:
        return "UUID_STRING()"

    def current_utc_expr(self) -> str:
        return "CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())"

    def effective_date_expr(self) -> str:
        return "TO_DATE('1900-01-01')"

    def expiry_date_expr(self) -> str:
        return "TO_DATE('2099-12-31')"

    def current_schema_sql(self) -> str:
        return "SELECT CURRENT_SCHEMA()"

    def drop_table_if_exists_sql(self, schema: str, table: str) -> str:
        return f'DROP TABLE IF EXISTS "{schema.upper()}"."{table.upper()}"'

    def hash_expr(self, col: str, xform: str = "") -> str:
        c = self._quote(col)
        if xform in ("SHA1_40", "SHA1"):
            return f"UPPER(SHA1_HEX(UPPER(TRIM({c}))))"
        elif xform == "SHA1_20":
            return f"LEFT(UPPER(SHA1_HEX(UPPER(TRIM({c})))), 20)"
        elif xform == "UPPER":
            return f"UPPER(TRIM({c}))"
        return f"TRIM({c})"

    def insert_select_sql(self, src_schema, src_table, tgt_schema, tgt_table,
                          col_pairs, pk_cols) -> str:
        tgt = self.qualified(tgt_schema, tgt_table)
        src = self.qualified(src_schema, src_table)
        tgt_cols = ", ".join(self._quote(c) for c, _ in col_pairs)
        src_expr = ", ".join(expr for _, expr in col_pairs)
        pk_join  = " AND ".join(
            f"tgt.{self._quote(p)} = src.{self._quote(p)}" for p in pk_cols)
        return (
            f"INSERT INTO {tgt} ({tgt_cols})\n"
            f"SELECT {src_expr}\n"
            f"FROM {src} src\n"
            f"WHERE NOT EXISTS (\n"
            f"    SELECT 1 FROM {tgt} tgt WHERE {pk_join}\n"
            f")"
        )

    def merge_sql(self, src_schema, src_table, tgt_schema, tgt_table,
                  col_pairs, pk_cols) -> str:
        tgt = self.qualified(tgt_schema, tgt_table)
        src = self.qualified(src_schema, src_table)
        pk_set   = {p.upper() for p in pk_cols}
        on_cls   = " AND ".join(
            f"tgt.{self._quote(p)} = src.{self._quote(p)}" for p in pk_cols)
        upd_cls  = ", ".join(
            f"tgt.{self._quote(c)} = {e}" for c, e in col_pairs
            if c.upper() not in pk_set)
        tgt_cols = ", ".join(self._quote(c) for c, _ in col_pairs)
        src_vals = ", ".join(e for _, e in col_pairs)
        return (
            f"MERGE INTO {tgt} tgt\n"
            f"USING (SELECT {src_vals} FROM {src}) src\n"
            f"ON ({on_cls})\n"
            f"WHEN MATCHED THEN UPDATE SET {upd_cls}\n"
            f"WHEN NOT MATCHED THEN INSERT ({tgt_cols}) VALUES ({src_vals})"
        )

    def audit_exprs(self, row_source: str = "PPDM_LOADER") -> dict:
        return {
            "ROW_CREATED_DATE":   self.current_utc_expr(),
            "ROW_CHANGED_DATE":   self.current_utc_expr(),
            "ROW_EFFECTIVE_DATE": self.effective_date_expr(),
            "ROW_EXPIRY_DATE":    self.expiry_date_expr(),
            "PPDM_GUID":          self.guid_expr(),
            "ACTIVE_IND":         "'Y'",
            "ROW_CREATED_BY":     f"'{row_source}'",
            "ROW_CHANGED_BY":     f"'{row_source}'",
        }

# ═══════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════

_DIALECTS: dict[str, type[DBDialect]] = {
    "sqlserver": SQLServerDialect,
    "oracle":    OracleDialect,
    "snowflake": SnowflakeDialect,
}


def get_dialect(engine = "sqlserver") -> DBDialect:
    """
    Return a dialect instance.
    Accepts either a string engine name ("sqlserver", "oracle", "snowflake")
    or a SQLAlchemy engine object (auto-detects dialect).
    """
    if not isinstance(engine, str):
        # Detect directly — no import from db.py to avoid circular import
        try:
            name = engine.dialect.name.lower()
            if "oracle" in name:
                engine = "oracle"
            elif "snowflake" in name:
                engine = "snowflake"
            else:
                engine = "sqlserver"
        except Exception:
            engine = "sqlserver"
    cls = _DIALECTS.get(engine.lower())
    if cls is None:
        supported = ", ".join(_DIALECTS)
        raise ValueError(
            f"Unsupported engine '{engine}'. Supported: {supported}"
        )
    return cls()


def register_dialect(name: str, cls: type[DBDialect]) -> None:
    """Register a custom dialect at runtime."""
    _DIALECTS[name.lower()] = cls


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Data Wrangler — db_dialect.py self-test")
    print("=" * 60)

    d = get_dialect("sqlserver")
    assert d.name == "sqlserver"

    print("\n[TEST 1] Identifier quoting")
    assert d.quote("my table") == "[my table]"
    assert d.qualified("dbo", "well") == "[dbo].[well]"
    print("  ✓  quote and qualified")

    print("\n[TEST 2] Server expressions")
    assert d.guid_expr()            == "NEWID()"
    assert d.current_utc_expr()     == "GETUTCDATE()"
    assert "1900" in d.effective_date_expr()
    assert "2099" in d.expiry_date_expr()
    print("  ✓  guid, timestamp, effective/expiry dates")

    print("\n[TEST 3] trim_expr")
    e = d.trim_expr("WELL_NAME")
    assert "LTRIM" in e and "RTRIM" in e and "NULLIF" in e and "CHAR(13)" in e
    print(f"  ✓  {e[:60]}...")

    print("\n[TEST 4] try_convert_date_expr")
    e = d.try_convert_date_expr("SPUD_DATE")
    assert "101" in e and "103" in e and "105" in e and "120" in e
    assert "CONVERT(varchar(10)" in e
    print(f"  ✓  {e[:60]}...")

    print("\n[TEST 5] bulk_load_sql")
    sql = d.bulk_load_sql(r"C:\data\wells.csv", "stg", "raw_data")
    assert "BULK INSERT" in sql and "FIELDTERMINATOR" in sql and "65001" in sql
    print(f"  ✓  {sql.splitlines()[0]}")

    print("\n[TEST 6] insert_select_sql")
    sql = d.insert_select_sql(
        "stg", "raw_data", "dbo", "well",
        col_pairs=[("UWI", "src.[UWI]"), ("WELL_NAME", "src.[WELL_NAME]")],
        pk_cols=["UWI"],
    )
    assert "INSERT INTO [dbo].[well]" in sql
    assert "NOT EXISTS" in sql
    print(f"  ✓  {sql.splitlines()[0]}")

    print("\n[TEST 7] merge_sql")
    sql = d.merge_sql(
        "stg", "raw_data", "dbo", "well",
        col_pairs=[("UWI", "src.[UWI]"), ("WELL_NAME", "src.[WELL_NAME]")],
        pk_cols=["UWI"],
    )
    assert "MERGE [dbo].[well]" in sql
    assert "WHEN MATCHED" in sql and "WHEN NOT MATCHED" in sql
    # UWI should not appear in UPDATE SET (it's a PK)
    assert "tgt.[WELL_NAME]" in sql
    print(f"  ✓  {sql.splitlines()[0]}")

    print("\n[TEST 8] get_dialect / registry")
    try:
        get_dialect("notanengine")
        assert False, "should have raised"
    except ValueError as e:
        assert "sqlserver" in str(e)
    print("  ✓  unknown engine raises ValueError with supported list")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)
