# GOVERNANCE DDL AND FUNCTIONS — append to file_inventory.py
# or keep as a standalone module imported by file_inventory.py

import hashlib
import datetime
from sqlalchemy import text


# ─────────────────────────────────────────────────────────────────────────────
# DDL
# ─────────────────────────────────────────────────────────────────────────────

GOVERNANCE_DDL_SQLSERVER = """
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'file_catalog')
    EXEC('CREATE SCHEMA file_catalog');

-- Users
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='file_catalog' AND t.name='INVENTORY_USER')
CREATE TABLE file_catalog.INVENTORY_USER (
    USER_ID        NVARCHAR(64)  NOT NULL PRIMARY KEY,   -- SHA256 of email
    FULL_NAME      NVARCHAR(200) NOT NULL,
    EMAIL          NVARCHAR(200) NOT NULL UNIQUE,
    PASSWORD_HASH  NVARCHAR(64)  NOT NULL,               -- SHA256 of password
    ROLE           NVARCHAR(20)  NOT NULL DEFAULT 'CATALOGER', -- MANAGER/DELEGATE/CATALOGER/USER
    ACTIVE_IND     NVARCHAR(1)   NOT NULL DEFAULT 'Y',
    LAST_LOGIN     DATETIME2     NULL,
    CREATED_DATE   DATETIME2     NOT NULL DEFAULT GETDATE(),
    CREATED_BY     NVARCHAR(64)  NULL
);

-- Groups
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='file_catalog' AND t.name='INVENTORY_GROUP')
CREATE TABLE file_catalog.INVENTORY_GROUP (
    GROUP_ID       NVARCHAR(64)  NOT NULL PRIMARY KEY,
    GROUP_NAME     NVARCHAR(200) NOT NULL,
    DESCRIPTION    NVARCHAR(500) NULL,
    FILE_TYPE      NVARCHAR(20)  NULL,
    ROOT_PATH      NVARCHAR(500) NULL,
    TOTAL_FILES    INT           NOT NULL DEFAULT 0,
    STATUS         NVARCHAR(20)  NOT NULL DEFAULT 'OPEN',  -- OPEN/IN_PROGRESS/CLOSED
    CREATED_BY     NVARCHAR(64)  NULL,
    CREATED_DATE   DATETIME2     NOT NULL DEFAULT GETDATE()
);

-- Assignments (one per assignee per group)
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='file_catalog' AND t.name='INVENTORY_ASSIGNMENT')
CREATE TABLE file_catalog.INVENTORY_ASSIGNMENT (
    ASSIGNMENT_ID  NVARCHAR(64)  NOT NULL PRIMARY KEY,
    GROUP_ID       NVARCHAR(64)  NOT NULL,
    ASSIGNED_TO    NVARCHAR(64)  NOT NULL,               -- FK INVENTORY_USER.USER_ID
    ASSIGNED_BY    NVARCHAR(64)  NOT NULL,
    ASSIGNED_DATE  DATETIME2     NOT NULL DEFAULT GETDATE(),
    DUE_DATE       DATE          NULL,
    COMPLETED_DATE DATETIME2     NULL,
    STATUS         NVARCHAR(20)  NOT NULL DEFAULT 'OPEN',
    NOTES          NVARCHAR(1000) NULL,
    FILE_COUNT     INT           NOT NULL DEFAULT 0
);

-- Extension history
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='file_catalog' AND t.name='ASSIGNMENT_EXTENSION')
CREATE TABLE file_catalog.ASSIGNMENT_EXTENSION (
    EXTENSION_ID      NVARCHAR(64) NOT NULL PRIMARY KEY,
    ASSIGNMENT_ID     NVARCHAR(64) NOT NULL,
    ORIGINAL_DUE_DATE DATE         NOT NULL,
    NEW_DUE_DATE      DATE         NOT NULL,
    EXTENDED_BY       NVARCHAR(64) NOT NULL,
    EXTENDED_DATE     DATETIME2    NOT NULL DEFAULT GETDATE(),
    REASON            NVARCHAR(500) NOT NULL
);

-- Group ↔ File junction
IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='file_catalog' AND t.name='INVENTORY_GROUP_FILE')
CREATE TABLE file_catalog.INVENTORY_GROUP_FILE (
    GROUP_FILE_ID  NVARCHAR(64)  NOT NULL PRIMARY KEY,
    GROUP_ID       NVARCHAR(64)  NOT NULL,
    ASSIGNMENT_ID  NVARCHAR(64)  NOT NULL,
    INVENTORY_ID   NVARCHAR(64)  NOT NULL,               -- FK GLOBAL_FILE_CATALOG
    ADDED_BY       NVARCHAR(64)  NULL,
    ADDED_DATE     DATETIME2     NOT NULL DEFAULT GETDATE(),
    CATALOGED_IND  NVARCHAR(1)   NOT NULL DEFAULT 'N',
    CATALOGED_DATE DATETIME2     NULL,
    SKIPPED_IND    NVARCHAR(1)   NOT NULL DEFAULT 'N',
    SKIP_REASON    NVARCHAR(500) NULL
);
"""


GOVERNANCE_DDL_ORACLE = """
DECLARE
BEGIN
    -- INVENTORY_USER
    BEGIN
        EXECUTE IMMEDIATE '
            CREATE TABLE FILE_CATALOG_INVENTORY_USER (
                USER_ID        VARCHAR2(64)  NOT NULL PRIMARY KEY,
                FULL_NAME      VARCHAR2(200) NOT NULL,
                EMAIL          VARCHAR2(200) NOT NULL UNIQUE,
                PASSWORD_HASH  VARCHAR2(64)  NOT NULL,
                ROLE           VARCHAR2(20)  DEFAULT ''CATALOGER'' NOT NULL, -- MANAGER/DELEGATE/CATALOGER/USER
                ACTIVE_IND     VARCHAR2(1)   DEFAULT ''Y'' NOT NULL,
                LAST_LOGIN     TIMESTAMP     NULL,
                CREATED_DATE   TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
                CREATED_BY     VARCHAR2(64)  NULL
            )';
    EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
    END;

    BEGIN
        EXECUTE IMMEDIATE '
            CREATE TABLE FILE_CATALOG_INVENTORY_GROUP (
                GROUP_ID       VARCHAR2(64)  NOT NULL PRIMARY KEY,
                GROUP_NAME     VARCHAR2(200) NOT NULL,
                DESCRIPTION    VARCHAR2(500) NULL,
                FILE_TYPE      VARCHAR2(20)  NULL,
                ROOT_PATH      VARCHAR2(500) NULL,
                TOTAL_FILES    NUMBER(10)    DEFAULT 0 NOT NULL,
                STATUS         VARCHAR2(20)  DEFAULT ''OPEN'' NOT NULL,
                CREATED_BY     VARCHAR2(64)  NULL,
                CREATED_DATE   TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
            )';
    EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
    END;

    BEGIN
        EXECUTE IMMEDIATE '
            CREATE TABLE FILE_CATALOG_INVENTORY_ASSIGNMENT (
                ASSIGNMENT_ID  VARCHAR2(64)   NOT NULL PRIMARY KEY,
                GROUP_ID       VARCHAR2(64)   NOT NULL,
                ASSIGNED_TO    VARCHAR2(64)   NOT NULL,
                ASSIGNED_BY    VARCHAR2(64)   NOT NULL,
                ASSIGNED_DATE  TIMESTAMP      DEFAULT SYSTIMESTAMP NOT NULL,
                DUE_DATE       DATE           NULL,
                COMPLETED_DATE TIMESTAMP      NULL,
                STATUS         VARCHAR2(20)   DEFAULT ''OPEN'' NOT NULL,
                NOTES          VARCHAR2(1000) NULL,
                FILE_COUNT     NUMBER(10)     DEFAULT 0 NOT NULL
            )';
    EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
    END;

    BEGIN
        EXECUTE IMMEDIATE '
            CREATE TABLE FILE_CATALOG_ASSIGNMENT_EXTENSION (
                EXTENSION_ID      VARCHAR2(64)  NOT NULL PRIMARY KEY,
                ASSIGNMENT_ID     VARCHAR2(64)  NOT NULL,
                ORIGINAL_DUE_DATE DATE          NOT NULL,
                NEW_DUE_DATE      DATE          NOT NULL,
                EXTENDED_BY       VARCHAR2(64)  NOT NULL,
                EXTENDED_DATE     TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
                REASON            VARCHAR2(500) NOT NULL
            )';
    EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
    END;

    BEGIN
        EXECUTE IMMEDIATE '
            CREATE TABLE FILE_CATALOG_INVENTORY_GROUP_FILE (
                GROUP_FILE_ID  VARCHAR2(64) NOT NULL PRIMARY KEY,
                GROUP_ID       VARCHAR2(64) NOT NULL,
                ASSIGNMENT_ID  VARCHAR2(64) NOT NULL,
                INVENTORY_ID   VARCHAR2(64) NOT NULL,
                ADDED_BY       VARCHAR2(64) NULL,
                ADDED_DATE     TIMESTAMP    DEFAULT SYSTIMESTAMP NOT NULL
            )';
    EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
    END;
END;
"""


GOVERNANCE_DDL_SNOWFLAKE = """
CREATE SCHEMA IF NOT EXISTS FILE_CATALOG;

CREATE TABLE IF NOT EXISTS FILE_CATALOG.INVENTORY_USER (
    USER_ID        VARCHAR(64)   NOT NULL PRIMARY KEY,
    FULL_NAME      VARCHAR(200)  NOT NULL,
    EMAIL          VARCHAR(200)  NOT NULL UNIQUE,
    PASSWORD_HASH  VARCHAR(64)   NOT NULL,
    ROLE           VARCHAR(20)   NOT NULL DEFAULT 'CATALOGER', -- MANAGER/DELEGATE/CATALOGER/USER
    ACTIVE_IND     VARCHAR(1)    NOT NULL DEFAULT 'Y',
    LAST_LOGIN     TIMESTAMP_NTZ NULL,
    CREATED_DATE   TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CREATED_BY     VARCHAR(64)   NULL
);

CREATE TABLE IF NOT EXISTS FILE_CATALOG.INVENTORY_GROUP (
    GROUP_ID       VARCHAR(64)   NOT NULL PRIMARY KEY,
    GROUP_NAME     VARCHAR(200)  NOT NULL,
    DESCRIPTION    VARCHAR(500)  NULL,
    FILE_TYPE      VARCHAR(20)   NULL,
    ROOT_PATH      VARCHAR(500)  NULL,
    TOTAL_FILES    INT           NOT NULL DEFAULT 0,
    STATUS         VARCHAR(20)   NOT NULL DEFAULT 'OPEN',
    CREATED_BY     VARCHAR(64)   NULL,
    CREATED_DATE   TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS FILE_CATALOG.INVENTORY_ASSIGNMENT (
    ASSIGNMENT_ID  VARCHAR(64)   NOT NULL PRIMARY KEY,
    GROUP_ID       VARCHAR(64)   NOT NULL,
    ASSIGNED_TO    VARCHAR(64)   NOT NULL,
    ASSIGNED_BY    VARCHAR(64)   NOT NULL,
    ASSIGNED_DATE  TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    DUE_DATE       DATE          NULL,
    COMPLETED_DATE TIMESTAMP_NTZ NULL,
    STATUS         VARCHAR(20)   NOT NULL DEFAULT 'OPEN',
    NOTES          VARCHAR(1000) NULL,
    FILE_COUNT     INT           NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS FILE_CATALOG.ASSIGNMENT_EXTENSION (
    EXTENSION_ID      VARCHAR(64)  NOT NULL PRIMARY KEY,
    ASSIGNMENT_ID     VARCHAR(64)  NOT NULL,
    ORIGINAL_DUE_DATE DATE         NOT NULL,
    NEW_DUE_DATE      DATE         NOT NULL,
    EXTENDED_BY       VARCHAR(64)  NOT NULL,
    EXTENDED_DATE     TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    REASON            VARCHAR(500) NOT NULL
);

CREATE TABLE IF NOT EXISTS FILE_CATALOG.INVENTORY_GROUP_FILE (
    GROUP_FILE_ID  VARCHAR(64)   NOT NULL PRIMARY KEY,
    GROUP_ID       VARCHAR(64)   NOT NULL,
    ASSIGNMENT_ID  VARCHAR(64)   NOT NULL,
    INVENTORY_ID   VARCHAR(64)   NOT NULL,
    ADDED_BY       VARCHAR(64)   NULL,
    ADDED_DATE     TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
"""



def migrate_group_file_columns(engine, dialect: str):
    """Add skip/catalog tracking columns to INVENTORY_GROUP_FILE if missing."""
    ftbl = _table(dialect, "INVENTORY_GROUP_FILE")
    cols = {
        "CATALOGED_IND":  ("NVARCHAR(1)   NOT NULL DEFAULT 'N'",  "VARCHAR2(1) DEFAULT 'N' NOT NULL",   "VARCHAR(1)   NOT NULL DEFAULT 'N'"),
        "CATALOGED_DATE": ("DATETIME2     NULL",                   "TIMESTAMP NULL",                      "TIMESTAMP_NTZ NULL"),
        "SKIPPED_IND":    ("NVARCHAR(1)   NOT NULL DEFAULT 'N'",   "VARCHAR2(1) DEFAULT 'N' NOT NULL",   "VARCHAR(1)   NOT NULL DEFAULT 'N'"),
        "SKIP_REASON":    ("NVARCHAR(500) NULL",                   "VARCHAR2(500) NULL",                  "VARCHAR(500) NULL"),
    }
    dialect_idx = {"mssql":0,"oracle":1,"snowflake":2}.get(dialect,0)
    with engine.begin() as conn:
        for col, defs in cols.items():
            col_def = defs[dialect_idx]
            try:
                if dialect == "mssql":
                    conn.execute(text(
                        f"IF NOT EXISTS (SELECT 1 FROM sys.columns c "
                        f"JOIN sys.tables t ON c.object_id=t.object_id "
                        f"JOIN sys.schemas s ON t.schema_id=s.schema_id "
                        f"WHERE s.name='file_catalog' AND t.name='INVENTORY_GROUP_FILE' "
                        f"AND c.name='{col}') "
                        f"ALTER TABLE {ftbl} ADD {col} {col_def}"
                    ))
                elif dialect == "oracle":
                    try:
                        conn.execute(text(f"ALTER TABLE {ftbl} ADD {col} {col_def}"))
                    except Exception:
                        pass
                else:
                    conn.execute(text(f"ALTER TABLE {ftbl} ADD COLUMN IF NOT EXISTS {col} {col_def}"))
            except Exception:
                pass


def _create_governance_indexes(engine, dialect: str):
    """
    Indexes on governance tables covering the main query patterns:
      INVENTORY_ASSIGNMENT : GROUP_ID, ASSIGNED_TO, STATUS
      INVENTORY_GROUP_FILE : ASSIGNMENT_ID, GROUP_ID, INVENTORY_ID
      INVENTORY_USER       : EMAIL (unique — already covered by constraint)
      ASSIGNMENT_EXTENSION : ASSIGNMENT_ID
    """
    from sqlalchemy import text

    def _safe(conn, sql):
        try:
            conn.execute(text(sql))
        except Exception:
            pass

    with engine.begin() as conn:
        if dialect == "mssql":
            def _ix(name, tbl, cols):
                return (
                    f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='{name}') "
                    f"CREATE INDEX [{name}] ON file_catalog.[{tbl}] ({cols})"
                )
            for sql in [
                _ix("IA_GROUP_IDX",      "INVENTORY_ASSIGNMENT",    "GROUP_ID"),
                _ix("IA_ASSIGNED_IDX",   "INVENTORY_ASSIGNMENT",    "ASSIGNED_TO"),
                _ix("IA_STATUS_IDX",     "INVENTORY_ASSIGNMENT",    "STATUS"),
                _ix("IA_DUE_IDX",        "INVENTORY_ASSIGNMENT",    "DUE_DATE"),
                _ix("IGF_ASGN_IDX",      "INVENTORY_GROUP_FILE",    "ASSIGNMENT_ID"),
                _ix("IGF_GROUP_IDX",     "INVENTORY_GROUP_FILE",    "GROUP_ID"),
                _ix("IGF_INV_IDX",       "INVENTORY_GROUP_FILE",    "INVENTORY_ID"),
                _ix("IGF_SKIP_IDX",      "INVENTORY_GROUP_FILE",    "SKIPPED_IND"),
                _ix("AE_ASGN_IDX",       "ASSIGNMENT_EXTENSION",    "ASSIGNMENT_ID"),
                _ix("IG_STATUS_IDX",     "INVENTORY_GROUP",         "STATUS"),
            ]:
                _safe(conn, sql)

        elif dialect == "oracle":
            def _ix(name, tbl, cols):
                return (
                    f"DECLARE BEGIN "
                    f"EXECUTE IMMEDIATE 'CREATE INDEX {name} ON FILE_CATALOG_{tbl} ({cols})'; "
                    f"EXCEPTION WHEN OTHERS THEN NULL; END;"
                )
            for sql in [
                _ix("IA_GROUP_IDX",    "INVENTORY_ASSIGNMENT",  "GROUP_ID"),
                _ix("IA_ASSIGNED_IDX", "INVENTORY_ASSIGNMENT",  "ASSIGNED_TO"),
                _ix("IA_STATUS_IDX",   "INVENTORY_ASSIGNMENT",  "STATUS"),
                _ix("IGF_ASGN_IDX",    "INVENTORY_GROUP_FILE",  "ASSIGNMENT_ID"),
                _ix("IGF_GROUP_IDX",   "INVENTORY_GROUP_FILE",  "GROUP_ID"),
                _ix("IGF_INV_IDX",     "INVENTORY_GROUP_FILE",  "INVENTORY_ID"),
                _ix("AE_ASGN_IDX",     "ASSIGNMENT_EXTENSION",  "ASSIGNMENT_ID"),
            ]:
                _safe(conn, sql)

        elif dialect == "snowflake":
            # Snowflake: cluster keys on the highest-cardinality lookup columns
            for sql in [
                'ALTER TABLE "FILE_CATALOG"."INVENTORY_ASSIGNMENT" '
                'CLUSTER BY (GROUP_ID, ASSIGNED_TO, STATUS)',
                'ALTER TABLE "FILE_CATALOG"."INVENTORY_GROUP_FILE" '
                'CLUSTER BY (ASSIGNMENT_ID, INVENTORY_ID)',
            ]:
                _safe(conn, sql)


def ensure_governance_schema(engine, dialect: str):
    """Create governance tables if they don't exist."""
    ddl_map = {
        "mssql": GOVERNANCE_DDL_SQLSERVER,
        "oracle": GOVERNANCE_DDL_ORACLE,
        "snowflake": GOVERNANCE_DDL_SNOWFLAKE,
    }
    ddl = ddl_map.get(dialect)
    if not ddl:
        raise ValueError(f"Unsupported dialect: {dialect}")

    with engine.begin() as conn:
        if dialect == "oracle":
            conn.execute(text(ddl))
        else:
            for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
                conn.execute(text(stmt))

    # Create indexes (idempotent)
    _create_governance_indexes(engine, dialect)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _new_id(seed: str = "") -> str:
    import uuid, time
    raw = f"{seed}{uuid.uuid4()}{time.time()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _user_id(email: str) -> str:
    return _sha256(email.lower().strip())


def _table(dialect: str, name: str) -> str:
    """Return dialect-appropriate table reference."""
    if dialect == "oracle":
        return f"FILE_CATALOG_{name}"
    elif dialect == "snowflake":
        return f'"FILE_CATALOG"."{name}"'
    else:
        return f"file_catalog.{name}"


# ─────────────────────────────────────────────────────────────────────────────
# User management
# ─────────────────────────────────────────────────────────────────────────────

def create_user(engine, dialect: str, full_name: str, email: str,
                password: str, role: str, created_by: str | None = None) -> str:
    """Insert a new user. Returns USER_ID. Raises if email exists."""
    uid = _user_id(email)
    tbl = _table(dialect, "INVENTORY_USER")
    with engine.begin() as conn:
        existing = conn.execute(
            text(f"SELECT USER_ID FROM {tbl} WHERE EMAIL = :e"),
            {"e": email.lower().strip()}
        ).fetchone()
        if existing:
            raise ValueError(f"Email {email} already registered.")
        conn.execute(text(f"""
            INSERT INTO {tbl}
                (USER_ID, FULL_NAME, EMAIL, PASSWORD_HASH, ROLE, ACTIVE_IND, CREATED_DATE, CREATED_BY)
            VALUES
                (:uid, :name, :email, :pw, :role, 'Y', {_now_expr(dialect)}, :cb)
        """), {
            "uid": uid,
            "name": full_name.strip(),
            "email": email.lower().strip(),
            "pw": _sha256(password),
            "role": role.upper(),
            "cb": created_by,
        })
    return uid


def authenticate_user(engine, dialect: str, email: str, password: str) -> dict | None:
    """Return user dict on success, None on failure."""
    tbl = _table(dialect, "INVENTORY_USER")
    with engine.begin() as conn:
        row = conn.execute(text(f"""
            SELECT USER_ID, FULL_NAME, EMAIL, ROLE, ACTIVE_IND
            FROM {tbl}
            WHERE EMAIL = :e AND PASSWORD_HASH = :pw AND ACTIVE_IND = 'Y'
        """), {"e": email.lower().strip(), "pw": _sha256(password)}).fetchone()
        if not row:
            return None
        # update last login
        conn.execute(text(f"""
            UPDATE {tbl} SET LAST_LOGIN = {_now_expr(dialect)}
            WHERE USER_ID = :uid
        """), {"uid": row[0]})
        return {"user_id": row[0], "full_name": row[1],
                "email": row[2], "role": row[3]}


def change_password(engine, dialect: str, user_id: str,
                    old_password: str, new_password: str) -> bool:
    tbl = _table(dialect, "INVENTORY_USER")
    with engine.begin() as conn:
        row = conn.execute(text(f"""
            SELECT USER_ID FROM {tbl}
            WHERE USER_ID = :uid AND PASSWORD_HASH = :pw
        """), {"uid": user_id, "pw": _sha256(old_password)}).fetchone()
        if not row:
            return False
        conn.execute(text(f"""
            UPDATE {tbl} SET PASSWORD_HASH = :pw WHERE USER_ID = :uid
        """), {"pw": _sha256(new_password), "uid": user_id})
    return True


def reset_password(engine, dialect: str, target_user_id: str, new_password: str):
    """Manager action — no old password required."""
    tbl = _table(dialect, "INVENTORY_USER")
    with engine.begin() as conn:
        conn.execute(text(f"""
            UPDATE {tbl} SET PASSWORD_HASH = :pw WHERE USER_ID = :uid
        """), {"pw": _sha256(new_password), "uid": target_user_id})


def list_users(engine, dialect: str) -> list[dict]:
    tbl = _table(dialect, "INVENTORY_USER")
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT USER_ID, FULL_NAME, EMAIL, ROLE, ACTIVE_IND, LAST_LOGIN, CREATED_DATE
            FROM {tbl} ORDER BY FULL_NAME
        """)).fetchall()
    return [dict(zip(["user_id","full_name","email","role","active_ind",
                      "last_login","created_date"], r)) for r in rows]


def set_user_active(engine, dialect: str, user_id: str, active: bool):
    tbl = _table(dialect, "INVENTORY_USER")
    val = "Y" if active else "N"
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE {tbl} SET ACTIVE_IND = :v WHERE USER_ID = :uid"),
                     {"v": val, "uid": user_id})


def has_any_user(engine, dialect: str) -> bool:
    tbl = _table(dialect, "INVENTORY_USER")
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).fetchone()
    return row[0] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Group & Assignment management
# ─────────────────────────────────────────────────────────────────────────────

def create_group_and_assign(engine, dialect: str, group_name: str,
                             description: str, file_type: str, root_path: str,
                             inventory_ids: list[str],
                             assignee_ids: list[str],
                             due_date,        # date object
                             created_by: str) -> str:
    """
    Create group, divide files evenly across assignees, insert INVENTORY_GROUP_FILE rows.
    Returns GROUP_ID.
    """
    group_id = _new_id(group_name)
    total = len(inventory_ids)
    n = len(assignee_ids)

    gtbl = _table(dialect, "INVENTORY_GROUP")
    atbl = _table(dialect, "INVENTORY_ASSIGNMENT")
    ftbl = _table(dialect, "INVENTORY_GROUP_FILE")

    # Divide files: floor division + remainder to first assignee
    base = total // n
    remainder = total % n
    slices = []
    idx = 0
    for i, uid in enumerate(assignee_ids):
        count = base + (1 if i < remainder else 0)
        slices.append((uid, inventory_ids[idx: idx + count]))
        idx += count

    with engine.begin() as conn:
        # Insert group
        conn.execute(text(f"""
            INSERT INTO {gtbl}
                (GROUP_ID, GROUP_NAME, DESCRIPTION, FILE_TYPE, ROOT_PATH,
                 TOTAL_FILES, STATUS, CREATED_BY, CREATED_DATE)
            VALUES
                (:gid, :name, :desc, :ft, :rp,
                 :total, 'OPEN', :cb, {_now_expr(dialect)})
        """), {"gid": group_id, "name": group_name, "desc": description,
               "ft": file_type, "rp": root_path, "total": total, "cb": created_by})

        # Insert assignments and file rows
        for assignee_id, file_slice in slices:
            aid = _new_id(assignee_id + group_id)
            conn.execute(text(f"""
                INSERT INTO {atbl}
                    (ASSIGNMENT_ID, GROUP_ID, ASSIGNED_TO, ASSIGNED_BY,
                     ASSIGNED_DATE, DUE_DATE, STATUS, FILE_COUNT)
                VALUES
                    (:aid, :gid, :at, :ab,
                     {_now_expr(dialect)}, :dd, 'OPEN', :fc)
            """), {"aid": aid, "gid": group_id, "at": assignee_id,
                   "ab": created_by, "dd": due_date, "fc": len(file_slice)})

            for inv_id in file_slice:
                conn.execute(text(f"""
                    INSERT INTO {ftbl}
                        (GROUP_FILE_ID, GROUP_ID, ASSIGNMENT_ID, INVENTORY_ID,
                         ADDED_BY, ADDED_DATE)
                    VALUES
                        (:gfid, :gid, :aid, :iid, :ab, {_now_expr(dialect)})
                """), {"gfid": _new_id(inv_id), "gid": group_id, "aid": aid,
                       "iid": inv_id, "ab": created_by})

    return group_id


def extend_assignment(engine, dialect: str, assignment_id: str,
                       new_due_date, extended_by: str, reason: str):
    atbl = _table(dialect, "INVENTORY_ASSIGNMENT")
    etbl = _table(dialect, "ASSIGNMENT_EXTENSION")
    with engine.begin() as conn:
        row = conn.execute(text(f"SELECT DUE_DATE FROM {atbl} WHERE ASSIGNMENT_ID = :aid"),
                           {"aid": assignment_id}).fetchone()
        if not row:
            raise ValueError("Assignment not found")
        original = row[0]
        ext_id = _new_id(assignment_id)
        conn.execute(text(f"""
            INSERT INTO {etbl}
                (EXTENSION_ID, ASSIGNMENT_ID, ORIGINAL_DUE_DATE, NEW_DUE_DATE,
                 EXTENDED_BY, EXTENDED_DATE, REASON)
            VALUES
                (:eid, :aid, :old, :new, :eb, {_now_expr(dialect)}, :reason)
        """), {"eid": ext_id, "aid": assignment_id, "old": original,
               "new": new_due_date, "eb": extended_by, "reason": reason})
        conn.execute(text(f"UPDATE {atbl} SET DUE_DATE = :new WHERE ASSIGNMENT_ID = :aid"),
                     {"new": new_due_date, "aid": assignment_id})


def mark_file_cataloged(engine, dialect: str, assignment_id: str, inventory_id: str,
                         user_id: str):
    """Mark a single file as cataloged; auto-complete assignment if all done."""
    # Update the underlying GLOBAL_FILE_CATALOG record (catalog status)
    # Table name depends on dialect — adjust prefix as needed
    gfc = _table(dialect, "GLOBAL_FILE_CATALOG") if dialect != "oracle" else "FILE_CATALOG_GLOBAL_FILE_CATALOG"
    atbl = _table(dialect, "INVENTORY_ASSIGNMENT")
    ftbl = _table(dialect, "INVENTORY_GROUP_FILE")

    with engine.begin() as conn:
        # Mark in junction table (could add a CATALOGED_IND column)
        # Check completion
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM {ftbl}
            WHERE ASSIGNMENT_ID = :aid
        """), {"aid": assignment_id}).fetchone()[0]

        # For now just check if all files in GLOBAL_FILE_CATALOG are cataloged
        cataloged = conn.execute(text(f"""
            SELECT COUNT(*) FROM {ftbl} f
            JOIN {gfc} g ON f.INVENTORY_ID = g.INVENTORY_ID
            WHERE f.ASSIGNMENT_ID = :aid
              AND g.CATALOG_STATUS = 'CATALOGED'
        """), {"aid": assignment_id}).fetchone()[0]

        if cataloged >= total:
            conn.execute(text(f"""
                UPDATE {atbl}
                SET STATUS = 'COMPLETED', COMPLETED_DATE = {_now_expr(dialect)}
                WHERE ASSIGNMENT_ID = :aid
            """), {"aid": assignment_id})


def get_my_assignments(engine, dialect: str, user_id: str) -> list[dict]:
    atbl = _table(dialect, "INVENTORY_ASSIGNMENT")
    gtbl = _table(dialect, "INVENTORY_GROUP")
    utbl = _table(dialect, "INVENTORY_USER")
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT a.ASSIGNMENT_ID, g.GROUP_NAME, g.FILE_TYPE, g.ROOT_PATH,
                   a.DUE_DATE, a.STATUS, a.FILE_COUNT,
                   u.FULL_NAME AS ASSIGNED_BY_NAME
            FROM {atbl} a
            JOIN {gtbl} g ON a.GROUP_ID = g.GROUP_ID
            JOIN {utbl} u ON a.ASSIGNED_BY = u.USER_ID
            WHERE a.ASSIGNED_TO = :uid
            ORDER BY a.DUE_DATE ASC
        """), {"uid": user_id}).fetchall()
    cols = ["assignment_id","group_name","file_type","root_path",
            "due_date","status","file_count","assigned_by_name"]
    return [dict(zip(cols, r)) for r in rows]


def get_all_groups(engine, dialect: str) -> list[dict]:
    gtbl = _table(dialect, "INVENTORY_GROUP")
    atbl = _table(dialect, "INVENTORY_ASSIGNMENT")
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT g.GROUP_ID, g.GROUP_NAME, g.FILE_TYPE, g.ROOT_PATH,
                   g.TOTAL_FILES, g.STATUS, g.CREATED_DATE,
                   COUNT(a.ASSIGNMENT_ID) AS ASSIGNEE_COUNT,
                   SUM(CASE WHEN a.STATUS='COMPLETED' THEN 1 ELSE 0 END) AS COMPLETED_COUNT
            FROM {gtbl} g
            LEFT JOIN {atbl} a ON g.GROUP_ID = a.GROUP_ID
            GROUP BY g.GROUP_ID, g.GROUP_NAME, g.FILE_TYPE, g.ROOT_PATH,
                     g.TOTAL_FILES, g.STATUS, g.CREATED_DATE
            ORDER BY g.CREATED_DATE DESC
        """)).fetchall()
    cols = ["group_id","group_name","file_type","root_path","total_files",
            "status","created_date","assignee_count","completed_count"]
    return [dict(zip(cols, r)) for r in rows]


def get_assignment_files(engine, dialect: str, assignment_id: str) -> list[dict]:
    ftbl = _table(dialect, "INVENTORY_GROUP_FILE")
    # Join back to GLOBAL_FILE_CATALOG for path / status
    gfc = "file_catalog.GLOBAL_FILE_CATALOG" if dialect == "mssql" else \
          "FILE_CATALOG_GLOBAL_FILE_CATALOG" if dialect == "oracle" else \
          '"FILE_CATALOG"."GLOBAL_FILE_CATALOG"'
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT f.INVENTORY_ID, g.FILE_PATH, g.FILE_NAME, g.FILE_EXT,
                   g.FILE_SIZE_MB, g.CATALOG_STATUS
            FROM {ftbl} f
            JOIN {gfc} g ON f.INVENTORY_ID = g.INVENTORY_ID
            WHERE f.ASSIGNMENT_ID = :aid
            ORDER BY g.FILE_PATH
        """), {"aid": assignment_id}).fetchall()
    cols = ["inventory_id","file_path","file_name","file_ext","file_size_mb","catalog_status"]
    return [dict(zip(cols, r)) for r in rows]


def get_extension_history(engine, dialect: str, assignment_id: str) -> list[dict]:
    etbl = _table(dialect, "ASSIGNMENT_EXTENSION")
    utbl = _table(dialect, "INVENTORY_USER")
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT e.ORIGINAL_DUE_DATE, e.NEW_DUE_DATE, u.FULL_NAME, e.EXTENDED_DATE, e.REASON
            FROM {etbl} e
            JOIN {utbl} u ON e.EXTENDED_BY = u.USER_ID
            WHERE e.ASSIGNMENT_ID = :aid
            ORDER BY e.EXTENDED_DATE
        """), {"aid": assignment_id}).fetchall()
    cols = ["original_due","new_due","extended_by","extended_date","reason"]
    return [dict(zip(cols, r)) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Dialect helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_expr(dialect: str) -> str:
    return {"mssql": "GETDATE()", "oracle": "SYSTIMESTAMP",
            "snowflake": "CURRENT_TIMESTAMP()"}.get(dialect, "GETDATE()")
