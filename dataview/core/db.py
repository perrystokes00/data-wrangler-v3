"""
db.py  —  PPDM Loader · Module 1: Database Connection
=======================================================
Handles SQL Server and Oracle connection, health checks, and basic
query execution.  All database I/O for the rest of the app goes
through this module.

Dependencies:
    pip install sqlalchemy pyodbc       # SQL Server
    pip install oracledb                # Oracle
    pip install snowflake-connector-python snowflake-sqlalchemy  # Snowflake

Test:
    python db.py
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from sqlalchemy import create_engine, text, inspect
    from sqlalchemy.engine import Engine
    HAS_SQLA = True
except ImportError:
    HAS_SQLA = False


# ═══════════════════════════════════════════════════════════════════════
# CONNECTION CONFIG
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class DBConfig:
    """
    Holds all parameters needed to build a database connection.

    db_type:
        'sqlserver' — SQL Server via pyodbc
        'oracle'    — Oracle via oracledb (pure Python, no Instant Client needed)

    SQL Server authentication modes:
        windows_auth=True  →  Trusted Connection (Windows credentials)
        windows_auth=False →  SQL Server Auth (username + password required)

    Oracle connection:
        server   = hostname (e.g. 'localhost')
        port     = 1521
        database = service name (e.g. 'FREEPDB1')
        username + password always required
    """
    db_type:          str  = "sqlserver"    # 'sqlserver', 'oracle', or 'snowflake'
    server:           str  = "PERRY\\SQLEXPRESS"
    database:         str  = "PPDM39_DEMO_1"
    username:         str  = ""
    password:         str  = ""
    windows_auth:     bool = True       # SQL Server only
    driver:           str  = "ODBC Driver 17 for SQL Server"  # SQL Server only
    port:             int  = 1433
    timeout:          int  = 30
    fast_executemany: bool = True
    # Snowflake-specific
    account:          str  = ""              # e.g. BBCUJWW-ZE62438
    warehouse:        str  = "COMPUTE_WH"
    sf_schema:        str  = "DEMO"
    sf_auth:          str  = "snowflake"     # snowflake or externalbrowser

    def odbc_string(self) -> str:
        """
        Build a raw ODBC connection string (SQL Server only).
        Passed to SQLAlchemy via create_engine(..., creator=...) so the
        driver name is never URL-encoded — avoids IM002 on Driver 17/18.
        """
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
            f"DATABASE={self.database}",
            f"Connect Timeout={self.timeout}",
            "MARS_Connection=yes",      # multiple active result sets
            "Packet Size=32767",        # max packet size — reduces round trips
        ]
        if self.windows_auth:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={self.username}")
            parts.append(f"PWD={self.password}")
        # Driver 18 requires this to avoid certificate errors on localhost
        if "18" in self.driver:
            parts.append("TrustServerCertificate=yes")
        return ";".join(parts)

    def oracle_dsn(self) -> str:
        """Build Oracle DSN: host:port/service_name."""
        return f"{self.server}:{self.port}/{self.database}"

    def connection_string(self) -> str:
        """Legacy — kept for masked() display only."""
        if self.db_type == "oracle":
            return f"oracle://{self.username}:***@{self.oracle_dsn()}"
        return self.odbc_string()

    def masked(self) -> str:
        """Return connection string with password hidden (for display)."""
        if self.db_type == "oracle":
            return f"oracle://{self.username}:***@{self.oracle_dsn()}"
        if self.db_type == "snowflake":
            return f"snowflake://{self.username}:***@{self.account}/{self.database}/{self.sf_schema}"
        s = self.odbc_string()
        return s.replace(f"PWD={self.password}", "PWD=***") if self.password else s


# ═══════════════════════════════════════════════════════════════════════
# CONNECTION RESULT
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ConnectionResult:
    ok:      bool
    message: str
    engine:  Optional[object] = None
    version: str = ""


# ═══════════════════════════════════════════════════════════════════════
# CONNECT
# ═══════════════════════════════════════════════════════════════════════

def connect(config: DBConfig) -> ConnectionResult:
    """
    Create and test a database connection.
    Branches on config.db_type — 'sqlserver', 'oracle', or 'snowflake'.
    Returns ConnectionResult with ok=True + engine on success.
    """
    if config.db_type == "oracle":
        return _connect_oracle(config)
    if config.db_type == "snowflake":
        return _connect_snowflake(config)
    return _connect_sqlserver(config)


def _connect_sqlserver(config: DBConfig) -> ConnectionResult:
    """SQL Server connection via pyodbc + SQLAlchemy."""
    if not HAS_SQLA:
        return ConnectionResult(
            ok=False,
            message="sqlalchemy is not installed. Run: pip install sqlalchemy pyodbc"
        )
    try:
        import pyodbc
        from sqlalchemy import event
        odbc_str = config.odbc_string()

        def _creator():
            return pyodbc.connect(odbc_str)

        engine = create_engine(
            "mssql+pyodbc://",
            creator=_creator,
            fast_executemany=config.fast_executemany,
            pool_pre_ping=True,     # ~1ms liveness check on checkout; silently
                                    # swaps a fresh conn for a dead pooled one.
                                    # Prevents the 9-11s stalls when SQL Express
                                    # has dropped an idle pooled connection.
            pool_recycle=300,       # proactively retire conns older than 5 min
                                    # so they never go stale enough to be dropped.
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
        )

        # pyodbc connects with ARITHABORT OFF; under that setting the optimizer
        # can compile worse plans than SSMS for the identical query (the classic
        # "instant in SSMS, slow in the app" gap — e.g. an oversized sort memory
        # grant that stalls). Stamp ARITHABORT ON on every pooled connection so
        # the whole app gets SSMS-quality plans.
        @event.listens_for(engine, "connect")
        def _arithabort_on(dbapi_conn, conn_record):
            cur = dbapi_conn.cursor()
            cur.execute("SET ARITHABORT ON")
            cur.close()

        with engine.connect() as con:
            row = con.execute(text("SELECT @@VERSION AS v")).fetchone()
            version = str(row[0]).split("\n")[0] if row else "Unknown"

        return ConnectionResult(ok=True, message="Connected", engine=engine,
                                version=version)
    except Exception as exc:
        return ConnectionResult(ok=False, message=str(exc))


def _connect_oracle(config: DBConfig) -> ConnectionResult:
    """Oracle connection via oracledb (pure Python) + SQLAlchemy."""
    if not HAS_SQLA:
        return ConnectionResult(
            ok=False,
            message="sqlalchemy is not installed. Run: pip install sqlalchemy oracledb"
        )
    try:
        import oracledb
        # Pure Python mode — no Oracle Instant Client required
        oracledb.init_oracle_client()   # no-op in thin mode, safe to call
    except Exception:
        pass  # thin mode requires no init

    try:
        import oracledb
        dsn = config.oracle_dsn()

        def _creator():
            return oracledb.connect(
                user=config.username,
                password=config.password,
                dsn=dsn,
            )

        engine = create_engine(
            "oracle+oracledb://",
            creator=_creator,
            pool_size=2,
            max_overflow=2,
            pool_timeout=30,
            pool_pre_ping=True,         # verify connection before use
            pool_reset_on_return="rollback",  # clean state on return, no stale txns
        )
        with engine.connect() as con:
            row = con.execute(text(
                "SELECT banner FROM v$version WHERE ROWNUM = 1"
            )).fetchone()
            version = str(row[0]) if row else "Oracle (version unknown)"

        return ConnectionResult(ok=True, message="Connected", engine=engine,
                                version=version)
    except Exception as exc:
        return ConnectionResult(ok=False, message=str(exc))


def _connect_snowflake(config: DBConfig) -> ConnectionResult:
    """Snowflake connection — engine stored in db_pool for Streamlit persistence."""
    # Debug log
    try:
        with open("sf_connect_debug.log", "a") as _lf:
            _lf.write(f"account={config.account} user={config.username} "
                      f"pwd_len={len(config.password)} auth={config.sf_auth}\n")
    except Exception:
        pass
    if not HAS_SQLA:
        return ConnectionResult(ok=False, message="sqlalchemy not installed")
    try:
        import snowflake.connector
        # Build connection kwargs
        _kw = dict(
            account   = config.account,
            user      = config.username,
            database  = config.database,
            schema    = config.sf_schema,
            warehouse = config.warehouse,
            login_timeout = 120,
        )
        if config.sf_auth == "externalbrowser":
            _kw["authenticator"] = "externalbrowser"
        else:
            _kw["password"] = config.password

        # Authenticate FIRST (opens browser if SSO) — before creating engine
        _test_con = snowflake.connector.connect(**_kw)
        _cur = _test_con.cursor()
        _row = _cur.execute("SELECT CURRENT_VERSION()").fetchone()
        version = f"Snowflake {_row[0]}" if _row else "Snowflake"
        _cur.close()
        _test_con.close()

        # Now build SQLAlchemy engine using same credentials
        _kw2 = dict(**_kw)  # copy
        def _creator(_k=_kw2):
            return snowflake.connector.connect(**_k)
        engine = create_engine(
            "snowflake://not:used@placeholder/",
            creator=_creator,
            pool_size=2, max_overflow=2,
            pool_timeout=30, pool_pre_ping=False,
        )
        # Store in module-level pool
        try:
            from dataview.core.db_pool import set_engine as _se
            _se(engine, "snowflake")
        except Exception:
            pass
        return ConnectionResult(ok=True, message="Connected",
                                engine=engine, version=version)
    except Exception as exc:
        return ConnectionResult(ok=False, message=str(exc))


def connect_demo() -> ConnectionResult:
    """Return a demo ConnectionResult with no real engine."""
    return ConnectionResult(
        ok=True,
        message="Demo mode — no database connection",
        engine=None,
        version="Demo"
    )


# ═══════════════════════════════════════════════════════════════════════
# QUERY HELPERS
# ═══════════════════════════════════════════════════════════════════════

def ping(engine) -> bool:
    try:
        with engine.connect() as con:
            con.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def fetch_all(engine, sql: str, params: dict | None = None) -> list[dict]:
    try:
        with engine.connect() as con:
            result = con.execute(text(sql), params or {})
            cols = list(result.keys())
            return [dict(zip(cols, row)) for row in result.fetchall()]
    except Exception as exc:
        raise RuntimeError(f"fetch_all failed: {exc}") from exc


def execute(engine, sql: str, params: dict | None = None) -> int:
    try:
        with engine.begin() as con:
            result = con.execute(text(sql), params or {})
            return result.rowcount
    except Exception as exc:
        raise RuntimeError(f"execute failed: {exc}") from exc


def list_tables(engine, schema: str = "dbo") -> list[str]:
    try:
        insp = inspect(engine)
        return sorted(insp.get_table_names(schema=schema))
    except Exception:
        return []


def table_exists(engine, table_name: str, schema: str = "dbo") -> bool:
    # INFORMATION_SCHEMA.TABLES is supported by both SQL Server and Oracle 23c
    sql = (
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table"
    )
    try:
        rows = fetch_all(engine, sql, {"schema": schema, "table": table_name})
        return bool(rows) and list(rows[0].values())[0] != 0
    except Exception:
        # Oracle fallback using ALL_TABLES
        sql2 = (
            "SELECT COUNT(*) FROM ALL_TABLES "
            "WHERE OWNER = :schema AND TABLE_NAME = :table"
        )
        rows = fetch_all(engine, sql2, {
            "schema": schema.upper(),
            "table":  table_name.upper(),
        })
        return bool(rows) and list(rows[0].values())[0] != 0


def drop_table_if_exists(engine, table_name: str, schema: str = "dbo") -> None:
    """Drop a table if it exists — handles both SQL Server and Oracle syntax."""
    dialect = _detect_dialect(engine)
    if dialect == "oracle":
        # Oracle has no IF EXISTS — use exception handler
        try:
            execute(engine, f'DROP TABLE "{schema}"."{table_name}"')
        except Exception as exc:
            if "ORA-00942" not in str(exc):  # ORA-00942 = table does not exist
                raise
    elif dialect == "snowflake":
        execute(engine, f'DROP TABLE IF EXISTS "{schema}"."{table_name}"')
    else:
        execute(engine,
                f"IF OBJECT_ID('{schema}.{table_name}', 'U') IS NOT NULL "
                f"DROP TABLE [{schema}].[{table_name}]")


def _detect_dialect(engine) -> str:
    """Detect the database dialect from the engine's driver name."""
    try:
        name = engine.dialect.name.lower()
        if "oracle" in name:
            return "oracle"
        if "snowflake" in name:
            return "snowflake"
    except Exception:
        pass
    return "sqlserver"


def get_dialect(engine=None):
    """
    Return a DBDialect instance for the given engine.
    Accepts a SQLAlchemy engine, a string name, or None (defaults to sqlserver).
    Import is deferred inside the function to avoid circular imports.
    """
    if isinstance(engine, str):
        dialect_name = engine.lower()
    elif engine is None:
        dialect_name = "sqlserver"
    else:
        dialect_name = _detect_dialect(engine)

    # Deferred import — db_dialect.py must NOT be imported at module level
    # to avoid circular import chains through normalize.py
    from dataview.core.db_dialect import get_dialect as _gd
    return _gd(dialect_name)


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST  (run: python db.py)
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("PPDM Loader — Module 1: DB Connection Test")
    print("=" * 60)

    # Test 1: Demo mode
    print("\n[TEST 1] Demo mode connection")
    r = connect_demo()
    assert r.ok
    assert r.engine is None
    print(f"  ✓  ok={r.ok}  message='{r.message}'")

    # Test 2: Windows Auth ODBC string
    print("\n[TEST 2] Windows Auth ODBC string")
    cfg_win = DBConfig(db_type="sqlserver", server="myserver", database="PPDM_39",
                       windows_auth=True)
    cs = cfg_win.odbc_string()
    assert "Trusted_Connection=yes" in cs
    assert "Perry" not in cs
    assert "UID=" not in cs
    print(f"  ✓  {cfg_win.masked()}")

    # Test 3: SQL Auth ODBC string
    print("\n[TEST 3] SQL Auth ODBC string")
    cfg_sql = DBConfig(db_type="sqlserver", server="myserver", database="PPDM_39",
                       username="sa", password="secret", windows_auth=False)
    cs_sql = cfg_sql.odbc_string()
    assert "UID=sa" in cs_sql
    assert "PWD=secret" in cs_sql
    assert "Trusted_Connection" not in cs_sql
    assert "***" in cfg_sql.masked()
    print(f"  ✓  {cfg_sql.masked()}")

    # Test 4: Windows Auth never leaks username
    print("\n[TEST 4] Windows Auth never leaks username")
    cfg_leak = DBConfig(db_type="sqlserver", server="srv", database="db",
                        username="Perry", password="", windows_auth=True)
    cs_leak = cfg_leak.odbc_string()
    assert "Perry" not in cs_leak, "Windows Auth must not embed username in ODBC string"
    print(f"  ✓  Username not present in Windows Auth string")

    # Test 5: Oracle DSN format
    print("\n[TEST 5] Oracle DSN format")
    cfg_ora = DBConfig(db_type="oracle", server="localhost", port=1521,
                       database="FREEPDB1", username="Perry", password="Murd0212")
    dsn = cfg_ora.oracle_dsn()
    assert dsn == "localhost:1521/FREEPDB1"
    assert "***" in cfg_ora.masked()
    assert "Murd0212" not in cfg_ora.masked()
    print(f"  ✓  DSN={dsn}  masked={cfg_ora.masked()}")

    # Test 6: Live SQL Server (only if env vars set)
    srv = os.environ.get("PPDM_SERVER")
    db  = os.environ.get("PPDM_DB")
    win = os.environ.get("PPDM_WINAUTH", "1") == "1"
    usr = os.environ.get("PPDM_USER", "")
    pwd = os.environ.get("PPDM_PASS", "")

    if srv and db:
        print(f"\n[TEST 6] Live SQL Server connection to {srv}/{db}")
        cfg_live = DBConfig(db_type="sqlserver", server=srv, database=db,
                            windows_auth=win, username=usr, password=pwd)
        result = connect(cfg_live)
        if result.ok:
            print(f"  ✓  Connected. Server: {result.version}")
            print(f"  ✓  Ping: {ping(result.engine)}")
            tables = list_tables(result.engine)
            print(f"  ✓  Tables in dbo: {len(tables)} found")
        else:
            print(f"  ✗  Connection failed: {result.message}")
            sys.exit(1)
    else:
        print("\n[TEST 6] Live SQL Server test SKIPPED — set PPDM_SERVER and PPDM_DB to run")

    # Test 7: Live Oracle (only if env vars set)
    ora_host = os.environ.get("ORA_HOST")
    ora_svc  = os.environ.get("ORA_SERVICE")
    ora_usr  = os.environ.get("ORA_USER", "")
    ora_pwd  = os.environ.get("ORA_PASS", "")
    ora_port = int(os.environ.get("ORA_PORT", "1521"))

    if ora_host and ora_svc:
        print(f"\n[TEST 7] Live Oracle connection to {ora_host}:{ora_port}/{ora_svc}")
        cfg_ora_live = DBConfig(
            db_type="oracle", server=ora_host, port=ora_port,
            database=ora_svc, username=ora_usr, password=ora_pwd,
        )
        result = connect(cfg_ora_live)
        if result.ok:
            print(f"  ✓  Connected. Version: {result.version}")
            print(f"  ✓  Ping: {ping(result.engine)}")
        else:
            print(f"  ✗  Connection failed: {result.message}")
            sys.exit(1)
    else:
        print("\n[TEST 7] Live Oracle test SKIPPED — set ORA_HOST, ORA_SERVICE, ORA_USER, ORA_PASS to run")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)
