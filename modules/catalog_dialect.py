"""
modules/catalog_dialect.py
==========================
Dialect utilities for the file_catalog and las_catalog schemas.
Mirrors the approach in db_dialect.py but for catalog-owned DDL.

Supports: mssql (SQL Server), oracle, snowflake
"""
from __future__ import annotations


def detect_dialect(engine) -> str:
    """Detect dialect from engine URL."""
    url = str(engine.url).lower()
    if "oracle" in url:       return "oracle"
    if "snowflake" in url:    return "snowflake"
    return "mssql"


# ── Timestamp ─────────────────────────────────────────────────────────────────

def now_expr(dialect: str) -> str:
    return {
        "oracle":    "SYSTIMESTAMP",
        "snowflake": "CURRENT_TIMESTAMP()",
    }.get(dialect, "GETUTCDATE()")


# ── Date arithmetic ───────────────────────────────────────────────────────────

def dateadd_days(dialect: str, col: str, days: int) -> str:
    """Return SQL expression for col + N days."""
    if dialect == "oracle":
        return f"{col} + ({days})"
    if dialect == "snowflake":
        return f"DATEADD('day', {days}, {col})"
    return f"DATEADD(day, {days}, {col})"


# ── Row limit ─────────────────────────────────────────────────────────────────

def limit_clause(dialect: str, n: int, position: str = "suffix") -> str:
    """
    Return the row-limit clause.
    position='prefix' → 'TOP N'  (SQL Server, goes after SELECT)
    position='suffix' → 'FETCH FIRST N ROWS ONLY' or 'LIMIT N'
    """
    if dialect == "mssql":
        return f"TOP({n})" if position == "prefix" else ""
    if dialect == "oracle":
        return f"FETCH FIRST {n} ROWS ONLY" if position == "suffix" else ""
    # Snowflake
    return f"LIMIT {n}" if position == "suffix" else ""


def select_top(dialect: str, n: int, cols: str, table: str,
               where: str = "", order: str = "") -> str:
    """Build a SELECT with row limit that works on all dialects."""
    w = f"WHERE {where}" if where else ""
    o = f"ORDER BY {order}" if order else ""
    if dialect == "mssql":
        return f"SELECT TOP({n}) {cols} FROM {table} {w} {o}".strip()
    if dialect == "oracle":
        inner = f"SELECT {cols} FROM {table} {w} {o}".strip()
        return f"SELECT * FROM ({inner}) WHERE ROWNUM <= {n}"
    # Snowflake
    return f"SELECT {cols} FROM {table} {w} {o} LIMIT {n}".strip()


# ── Data types ────────────────────────────────────────────────────────────────

def varchar(dialect: str, n: int) -> str:
    if dialect == "oracle":    return f"NVARCHAR2({n})"
    if dialect == "snowflake": return f"VARCHAR({n})"
    return f"NVARCHAR({n})"


def timestamp_type(dialect: str) -> str:
    if dialect == "oracle":    return "TIMESTAMP"
    if dialect == "snowflake": return "TIMESTAMP_NTZ"
    return "DATETIME2"


def timestamp_default(dialect: str) -> str:
    return f"DEFAULT {now_expr(dialect)}"


# ── Identifier quoting ────────────────────────────────────────────────────────

def quote_ident(dialect: str, name: str) -> str:
    if dialect == "oracle":    return f'"{name.upper()}"'
    if dialect == "snowflake": return f'"{name}"'
    return f"[{name}]"


def schema_table(dialect: str, schema: str, table: str) -> str:
    if dialect == "oracle":
        return f'"{schema.upper()}"."{table.upper()}"'
    if dialect == "snowflake":
        return f'"{schema}"."{table}"'
    return f"[{schema}].[{table}]"


# ── DDL helpers ───────────────────────────────────────────────────────────────

def if_not_exists_table(dialect: str, schema: str, table: str,
                         ddl_body: str) -> str:
    """
    Wrap CREATE TABLE in an existence check for each dialect.
    ddl_body = everything after CREATE TABLE schema.name
    """
    if dialect == "oracle":
        # Oracle: use PL/SQL exception block
        tbl_upper = table.upper()
        sch_upper = schema.upper()
        return f"""
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM all_tables
    WHERE owner='{sch_upper}' AND table_name='{tbl_upper}';
    IF v_count = 0 THEN
        EXECUTE IMMEDIATE 'CREATE TABLE "{sch_upper}"."{tbl_upper}" {ddl_body}';
    END IF;
END;
"""
    if dialect == "snowflake":
        return (f'CREATE TABLE IF NOT EXISTS "{schema}"."{table}" '
                f'{ddl_body}')
    # SQL Server
    return f"""
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id=s.schema_id
    WHERE s.name='{schema}' AND t.name='{table}'
)
CREATE TABLE [{schema}].[{table}] {ddl_body}
"""


def create_schema_ddl(dialect: str, schema: str) -> str:
    """CREATE SCHEMA statement for each dialect."""
    if dialect == "oracle":
        # Oracle uses users/schemas — typically pre-created
        return f"-- Oracle: ensure user/schema '{schema.upper()}' exists"
    if dialect == "snowflake":
        return f'CREATE SCHEMA IF NOT EXISTS "{schema}"'
    return (f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='{schema}') "
            f"EXEC('CREATE SCHEMA [{schema}]')")


# ── Index creation ────────────────────────────────────────────────────────────

def create_index_ddl(dialect: str, schema: str, table: str,
                      index_name: str, cols: str) -> str:
    if dialect == "oracle":
        return (f'CREATE INDEX "{index_name}" '
                f'ON "{schema.upper()}"."{table.upper()}" ({cols})')
    if dialect == "snowflake":
        # Snowflake doesn't support traditional indexes — no-op
        return f"-- Snowflake: indexes not required for {index_name}"
    return (f"IF NOT EXISTS (SELECT 1 FROM sys.indexes i "
            f"JOIN sys.tables t ON i.object_id=t.object_id "
            f"JOIN sys.schemas s ON t.schema_id=s.schema_id "
            f"WHERE s.name='{schema}' AND t.name='{table}' "
            f"AND i.name='{index_name}') "
            f"CREATE INDEX [{index_name}] ON [{schema}].[{table}] ({cols})")
