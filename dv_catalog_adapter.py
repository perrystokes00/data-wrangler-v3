"""
modules/dv_catalog_adapter.py
==============================
DataView v3 adapter for the File Catalog system.

Bridges page_dv_catalog.py to the DataView schema — provides
doc type mappings, vault root, and governance table DDL.
"""
from __future__ import annotations

from pathlib import Path
from sqlalchemy import text

# ── Vault root — where files live ────────────────────────────────────
VAULT_ROOT = r"C:\Bulk"

# ── File type → (doc_type_group, doc_type) ───────────────────────────
_EXT_MAP = {
    # Well Logs
    ".las":    ("Well Logs",  "LAS"),
    ".dlis":   ("Well Logs",  "DLIS"),
    ".dl":     ("Well Logs",  "DLIS"),
    ".lis":    ("Well Logs",  "LIS"),
    # Seismic
    ".segy":   ("Seismic",    "SEGY"),
    ".sgy":    ("Seismic",    "SEGY"),
    ".seg2":   ("Seismic",    "SEG2"),
    ".seg":    ("Seismic",    "SEG2"),
    ".p190":   ("Seismic",    "P190"),
    ".p1":     ("Seismic",    "P190"),
    # Documents
    ".pdf":    ("Documents",  "PDF"),
    ".docx":   ("Documents",  "WORD"),
    ".doc":    ("Documents",  "WORD"),
    ".xlsx":   ("Documents",  "EXCEL"),
    ".xls":    ("Documents",  "EXCEL"),
    ".csv":    ("Tabular",    "CSV"),
    ".txt":    ("Tabular",    "TXT"),
    # Spatial
    ".shp":    ("Spatial",    "SHP"),
    ".geojson":("Spatial",    "GEOJSON"),
    ".kml":    ("Spatial",    "KML"),
    ".tif":    ("Images",     "TIFF"),
    ".tiff":   ("Images",     "TIFF"),
}


def get_doc_type(ext: str) -> tuple[str, str]:
    """Return (doc_type_group, doc_type) for a file extension."""
    return _EXT_MAP.get(ext.lower(), ("Other", "UNKNOWN"))


def ensure_vault(root: str = VAULT_ROOT) -> dict:
    """Create standard vault folder structure if it doesn't exist."""
    folders = {
        "raw":       Path(root) / "raw",
        "curated":   Path(root) / "curated",
        "enriched":  Path(root) / "enriched",
        "well_logs": Path(root) / "raw" / "well_logs",
        "seismic":   Path(root) / "raw" / "seismic",
        "documents": Path(root) / "raw" / "documents",
    }
    created = {}
    for name, path in folders.items():
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                created[name] = str(path)
            except Exception as e:
                created[name] = f"ERROR: {e}"
        else:
            created[name] = str(path)
    return created


# ── Governance DDL ────────────────────────────────────────────────────

_GOVERNANCE_DDL = [

    # Users
    """
    IF OBJECT_ID('dataview.dv_catalog_user','U') IS NULL
    CREATE TABLE dataview.dv_catalog_user (
        user_id         NVARCHAR(40)    NOT NULL,
        username        NVARCHAR(80)    NOT NULL,
        full_name       NVARCHAR(255)   NOT NULL,
        email           NVARCHAR(255)   NULL,
        password_hash   NVARCHAR(64)    NOT NULL,
        role            NVARCHAR(20)    NOT NULL DEFAULT 'CATALOGER',
        active_ind      NVARCHAR(1)     NOT NULL DEFAULT 'Y',
        last_login      DATETIME2       NULL,
        row_created_by  NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
        row_created_date DATETIME2      NOT NULL DEFAULT GETDATE(),
        CONSTRAINT pk_dv_catalog_user    PRIMARY KEY (user_id),
        CONSTRAINT uq_dv_catalog_user_un UNIQUE (username),
        CONSTRAINT ck_dv_catalog_user_r  CHECK (role IN ('MANAGER','DELEGATE','CATALOGER')),
        CONSTRAINT ck_dv_catalog_user_ai CHECK (active_ind IN ('Y','N'))
    )
    """,

    # Groups
    """
    IF OBJECT_ID('dataview.dv_catalog_group','U') IS NULL
    CREATE TABLE dataview.dv_catalog_group (
        group_id        NVARCHAR(40)    NOT NULL,
        group_name      NVARCHAR(255)   NOT NULL,
        description     NVARCHAR(1000)  NULL,
        doc_type_filter NVARCHAR(500)   NULL,
        root_path_filter NVARCHAR(1000) NULL,
        status_filter   NVARCHAR(40)    NULL DEFAULT 'UNCATALOGED',
        created_by      NVARCHAR(40)    NOT NULL,
        row_created_date DATETIME2      NOT NULL DEFAULT GETDATE(),
        active_ind      NVARCHAR(1)     NOT NULL DEFAULT 'Y',
        CONSTRAINT pk_dv_catalog_group   PRIMARY KEY (group_id),
        CONSTRAINT ck_dv_catalog_grp_ai  CHECK (active_ind IN ('Y','N'))
    )
    """,

    # Assignments — user to group
    """
    IF OBJECT_ID('dataview.dv_catalog_assignment','U') IS NULL
    CREATE TABLE dataview.dv_catalog_assignment (
        assignment_id   NVARCHAR(40)    NOT NULL,
        group_id        NVARCHAR(40)    NOT NULL,
        user_id         NVARCHAR(40)    NOT NULL,
        assigned_by     NVARCHAR(40)    NOT NULL,
        assigned_date   DATETIME2       NOT NULL DEFAULT GETDATE(),
        completed_date  DATETIME2       NULL,
        status          NVARCHAR(20)    NOT NULL DEFAULT 'ACTIVE',
        notes           NVARCHAR(1000)  NULL,
        CONSTRAINT pk_dv_catalog_asgn   PRIMARY KEY (assignment_id),
        CONSTRAINT fk_dv_asgn_group     FOREIGN KEY (group_id)
            REFERENCES dataview.dv_catalog_group(group_id),
        CONSTRAINT fk_dv_asgn_user      FOREIGN KEY (user_id)
            REFERENCES dataview.dv_catalog_user(user_id)
    )
    """,

    # File assignments — inventory item to assignment
    """
    IF OBJECT_ID('dataview.dv_catalog_file_assignment','U') IS NULL
    CREATE TABLE dataview.dv_catalog_file_assignment (
        file_assignment_id  NVARCHAR(40)  NOT NULL,
        assignment_id       NVARCHAR(40)  NOT NULL,
        inventory_id        NVARCHAR(40)  NOT NULL,
        status              NVARCHAR(20)  NOT NULL DEFAULT 'PENDING',
        completed_date      DATETIME2     NULL,
        completed_by        NVARCHAR(40)  NULL,
        notes               NVARCHAR(1000) NULL,
        CONSTRAINT pk_dv_catalog_fa     PRIMARY KEY (file_assignment_id),
        CONSTRAINT fk_dv_fa_asgn        FOREIGN KEY (assignment_id)
            REFERENCES dataview.dv_catalog_assignment(assignment_id),
        CONSTRAINT fk_dv_fa_inv         FOREIGN KEY (inventory_id)
            REFERENCES dataview.dv_global_file_catalog(inventory_id)
    )
    """,
]


def ensure_governance_schema(engine) -> list[str]:
    """
    Create governance tables if they don't exist.
    Returns list of any errors encountered.
    """
    errors = []
    for ddl in _GOVERNANCE_DDL:
        try:
            with engine.begin() as con:
                con.execute(text(ddl.strip()))
        except Exception as e:
            errors.append(str(e))
    return errors


def get_users(engine) -> list[dict]:
    """Return all active catalog users."""
    try:
        with engine.connect() as con:
            rows = con.execute(text("""
                SELECT user_id, username, full_name, email, role,
                       active_ind, last_login, row_created_date
                FROM dataview.dv_catalog_user
                WHERE active_ind = 'Y'
                ORDER BY full_name
            """)).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def authenticate(engine, username: str, password_hash: str) -> dict | None:
    """
    Authenticate a user. Returns user dict or None.
    password_hash should be SHA256 hex of the password.
    """
    try:
        with engine.connect() as con:
            row = con.execute(text("""
                SELECT user_id, username, full_name, email, role
                FROM dataview.dv_catalog_user
                WHERE username      = :u
                  AND password_hash = :p
                  AND active_ind    = 'Y'
            """), {"u": username, "p": password_hash}).mappings().fetchone()
        if row:
            # Update last login
            with engine.begin() as con:
                con.execute(text("""
                    UPDATE dataview.dv_catalog_user
                    SET last_login = GETDATE()
                    WHERE username = :u
                """), {"u": username})
            return dict(row)
        return None
    except Exception:
        return None


def create_user(engine, username: str, full_name: str,
                email: str, password_hash: str, role: str,
                created_by: str) -> tuple[bool, str]:
    """Create a new catalog user. Returns (ok, message)."""
    import uuid
    user_id = str(uuid.uuid4())
    try:
        with engine.begin() as con:
            con.execute(text("""
                INSERT INTO dataview.dv_catalog_user
                    (user_id, username, full_name, email,
                     password_hash, role, active_ind,
                     row_created_by, row_created_date)
                VALUES
                    (:uid, :un, :fn, :em,
                     :ph, :role, 'Y',
                     :cb, GETDATE())
            """), {"uid": user_id, "un": username, "fn": full_name,
                   "em": email, "ph": password_hash,
                   "role": role, "cb": created_by})
        return True, f"User {username} created"
    except Exception as e:
        if "UNIQUE" in str(e) or "duplicate" in str(e).lower():
            return False, f"Username '{username}' already exists"
        return False, str(e)


def is_first_user(engine) -> bool:
    """True if no users exist yet — first user gets MANAGER role."""
    try:
        with engine.connect() as con:
            n = con.execute(text(
                "SELECT COUNT(*) FROM dataview.dv_catalog_user"
            )).scalar()
        return (n or 0) == 0
    except Exception:
        return True
