"""
WranglerView configuration.
Connection strings, paths, and defaults.
"""
import os

# Load .env so SNOWFLAKE_* (including the private-key path) is available to
# every module that imports config. Best-effort: ignore if python-dotenv
# isn't installed or there's no .env file.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ── Database connections ──────────────────────────────────────────

# SQL Server (prototype / local development)
SQLSERVER_CONN = (
    "mssql+pyodbc://127.0.0.1\\SQLEXPRESS/WranglerView"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
    "&TrustServerCertificate=yes"
)

# ── Snowflake (production federation) ─────────────────────────────
# Snowflake now blocks password-only logins, so the connection uses
# KEY-PAIR authentication. Build the engine via get_snowflake_engine();
# do NOT build a username/password URL anymore.
#
# Required in .env:
#   SNOWFLAKE_ACCOUNT=YDWXNCV-VL88062
#   SNOWFLAKE_USER=PMSTOKES00
#   SNOWFLAKE_PRIVATE_KEY_PATH=C:\path\to\rsa_key.p8
#   SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=        # blank if key made with -nocrypt
#
# Optional overrides (defaults below preserve the previous connection):
SNOWFLAKE_DATABASE  = os.environ.get("SNOWFLAKE_DATABASE",  "WELL_FEDERATION")
SNOWFLAKE_SCHEMA    = os.environ.get("SNOWFLAKE_SCHEMA",    "CURATED")
SNOWFLAKE_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "WV_WH")
SNOWFLAKE_ROLE      = os.environ.get("SNOWFLAKE_ROLE",      "WV_ROLE")

# DEPRECATED: kept only so old `from config import SNOWFLAKE_CONN` imports
# don't break. It no longer works (password auth is blocked). Anything still
# using it should switch to get_snowflake_engine().
SNOWFLAKE_CONN = None

_SF_ENGINE = None  # module-level singleton — survives Streamlit reruns
_PK_DER = None     # cached private-key bytes


def get_snowflake_private_key():
    """DER/PKCS8 private-key bytes for key-pair auth (cached).

    The single source every raw connect() call should use:
        snowflake.connector.connect(..., private_key=config.get_snowflake_private_key())
    instead of password=os.environ.get("SNOWFLAKE_PASSWORD", "").
    """
    global _PK_DER
    if _PK_DER is None:
        _PK_DER = _load_private_key_der()
    return _PK_DER


def _load_private_key_der() -> bytes:
    """Read the PEM private key and return DER/PKCS8 bytes for the driver."""
    from cryptography.hazmat.primitives import serialization

    path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    if not path:
        raise RuntimeError("SNOWFLAKE_PRIVATE_KEY_PATH is not set in your .env")
    if not os.path.exists(path):
        raise RuntimeError(f"Snowflake private key not found at: {path}")

    passphrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None
    with open(path, "rb") as fh:
        key = serialization.load_pem_private_key(
            fh.read(),
            password=passphrase.encode() if passphrase else None,
        )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def get_snowflake_engine():
    """Key-pair-authenticated Snowflake engine (cached singleton).
    Use this everywhere in place of create_engine(SNOWFLAKE_CONN).
    Fails fast: config/auth problems raise here, not on first query."""
    global _SF_ENGINE
    if _SF_ENGINE is not None:
        return _SF_ENGINE

    from sqlalchemy import create_engine
    from snowflake.sqlalchemy import URL

    account = os.environ.get("SNOWFLAKE_ACCOUNT", "")
    user    = os.environ.get("SNOWFLAKE_USER", "")
    if not account or not user:
        raise RuntimeError(
            "SNOWFLAKE_ACCOUNT and SNOWFLAKE_USER must be set in your .env")

    pkb = _load_private_key_der()
    engine = create_engine(
        URL(
            account=account,
            user=user,
            database=SNOWFLAKE_DATABASE,
            schema=SNOWFLAKE_SCHEMA,
            warehouse=SNOWFLAKE_WAREHOUSE,
            role=SNOWFLAKE_ROLE,
        ),
        connect_args={"private_key": pkb},
        pool_pre_ping=True,
    )
    with engine.connect() as conn:        # prove it now
        conn.exec_driver_sql("SELECT 1")
    _SF_ENGINE = engine
    return _SF_ENGINE


def get_snowflake_connection(**overrides):
    """Raw snowflake.connector connection via KEY-PAIR auth, for code that
    uses cursors rather than a SQLAlchemy engine (e.g. the federation loader
    and scout tickets).

    Defaults mirror the app's previous raw connections (role ACCOUNTADMIN,
    WELL_FEDERATION / WV_WH). Pass overrides such as role=... or
    autocommit=True to change or add connect() parameters.
    """
    import snowflake.connector

    params = dict(
        account=os.environ.get("SNOWFLAKE_ACCOUNT", "YDWXNCV-VL88062"),
        user=os.environ.get("SNOWFLAKE_USER", "PMSTOKES00"),
        private_key=_load_private_key_der(),
        database=SNOWFLAKE_DATABASE,
        warehouse=SNOWFLAKE_WAREHOUSE,
        role="ACCOUNTADMIN",
    )
    params.update(overrides)
    return snowflake.connector.connect(**params)


# Active connection — switch between SQL Server and Snowflake
DB_DIALECT = os.environ.get("WV_DIALECT", "sqlserver")  # "sqlserver" or "snowflake"

# ── Paths ─────────────────────────────────────────────────────────
GEOJSON_PATH = "wells.geojson"

# ── Mapbox ────────────────────────────────────────────────────────
MAPBOX_TOKEN = os.environ.get("MAPBOX_API_KEY", "")
