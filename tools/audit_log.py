"""
modules/audit_log.py
====================
Append-only application audit log — dialect aware (SQL Server, Oracle, Snowflake).
"""
from __future__ import annotations
import uuid, json
from sqlalchemy import text

LOGIN            = "LOGIN"
LOGOUT           = "LOGOUT"
IMPERSONATE      = "IMPERSONATE"
IMPERSONATE_EXIT = "IMPERSONATE_EXIT"
CATALOG          = "CATALOG"
SKIP             = "SKIP"
ASSIGN           = "ASSIGN"
REASSIGN         = "REASSIGN"
REMOVE_ASSIGN    = "REMOVE_ASSIGN"
PASSWORD_RESET   = "PASSWORD_RESET"
PASSWORD_CHANGE  = "PASSWORD_CHANGE"
EXPORT           = "EXPORT"
PPDM_UPDATE      = "PPDM_UPDATE"
USER_CREATE      = "USER_CREATE"
USER_DEACTIVATE  = "USER_DEACTIVATE"
USER_DELETE      = "USER_DELETE"
CRAWL            = "CRAWL"
CLEAR            = "CLEAR"

_AUDIT_OK = False


def _dialect(engine) -> str:
    url = str(engine.url).lower()
    if "oracle" in url:    return "oracle"
    if "snowflake" in url: return "snowflake"
    return "mssql"


def _now(dialect: str) -> str:
    return {"oracle": "SYSTIMESTAMP",
            "snowflake": "CURRENT_TIMESTAMP()"}.get(dialect, "GETUTCDATE()")


def _varchar(dialect: str, n: int) -> str:
    if dialect == "oracle":    return f"NVARCHAR2({n})"
    if dialect == "snowflake": return f"VARCHAR({n})"
    return f"NVARCHAR({n})"


def _ts_type(dialect: str) -> str:
    return {"oracle": "TIMESTAMP",
            "snowflake": "TIMESTAMP_NTZ"}.get(dialect, "DATETIME2")


def _tbl(dialect: str) -> str:
    if dialect == "oracle":    return '"FILE_CATALOG"."AUDIT_LOG"'
    if dialect == "snowflake": return '"FILE_CATALOG"."AUDIT_LOG"'
    return "file_catalog.AUDIT_LOG"


def _ddl(dialect: str) -> str:
    ts   = _ts_type(dialect)
    now  = _now(dialect)
    v40  = _varchar(dialect, 40)
    v50  = _varchar(dialect, 50)
    v255 = _varchar(dialect, 255)
    v500 = _varchar(dialect, 500)
    v1k  = _varchar(dialect, 1000)
    vmax = "CLOB" if dialect == "oracle" else "TEXT" if dialect == "snowflake" else "NVARCHAR(MAX)"

    if dialect == "oracle":
        return f"""
DECLARE v INTEGER;
BEGIN
    SELECT COUNT(*) INTO v FROM all_tables
    WHERE owner='FILE_CATALOG' AND table_name='AUDIT_LOG';
    IF v=0 THEN
        EXECUTE IMMEDIATE 'CREATE TABLE "FILE_CATALOG"."AUDIT_LOG" (
            AUDIT_ID     {v40}   NOT NULL PRIMARY KEY,
            EVENT_TIME   {ts}    DEFAULT {now},
            EVENT_TYPE   {v50}   NOT NULL,
            USER_ID      {v40},
            USER_NAME    {v255},
            TARGET_ID    {v40},
            TARGET_TYPE  {v50},
            TARGET_NAME  {v500},
            OLD_VALUE    {vmax},
            NEW_VALUE    {vmax},
            NOTES        {v1k},
            SESSION_ID   {v40}
        )';
    END IF;
END;"""
    if dialect == "snowflake":
        return f"""
CREATE TABLE IF NOT EXISTS "FILE_CATALOG"."AUDIT_LOG" (
    AUDIT_ID     {v40}   NOT NULL PRIMARY KEY,
    EVENT_TIME   {ts}    DEFAULT {now},
    EVENT_TYPE   {v50}   NOT NULL,
    USER_ID      {v40},
    USER_NAME    {v255},
    TARGET_ID    {v40},
    TARGET_TYPE  {v50},
    TARGET_NAME  {v500},
    OLD_VALUE    {vmax},
    NEW_VALUE    {vmax},
    NOTES        {v1k},
    SESSION_ID   {v40}
)"""
    return f"""
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id=s.schema_id
    WHERE s.name='file_catalog' AND t.name='AUDIT_LOG'
)
CREATE TABLE file_catalog.AUDIT_LOG (
    AUDIT_ID     NVARCHAR(40)   NOT NULL PRIMARY KEY,
    EVENT_TIME   DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
    EVENT_TYPE   NVARCHAR(50)   NOT NULL,
    USER_ID      NVARCHAR(40)   NULL,
    USER_NAME    NVARCHAR(255)  NULL,
    TARGET_ID    NVARCHAR(40)   NULL,
    TARGET_TYPE  NVARCHAR(50)   NULL,
    TARGET_NAME  NVARCHAR(500)  NULL,
    OLD_VALUE    NVARCHAR(MAX)  NULL,
    NEW_VALUE    NVARCHAR(MAX)  NULL,
    NOTES        NVARCHAR(1000) NULL,
    SESSION_ID   NVARCHAR(40)   NULL
)"""


def ensure_audit_table(engine) -> bool:
    global _AUDIT_OK
    if _AUDIT_OK:
        return True
    try:
        d = _dialect(engine)
        with engine.begin() as con:
            con.execute(text(_ddl(d).strip()))
        _AUDIT_OK = True
        return True
    except Exception:
        return False


def audit(engine, event_type, user_id="", user_name="",
          target_id="", target_type="", target_name="",
          old_value=None, new_value=None, notes="", session_id=""):
    """Write one audit event. Never raises."""
    try:
        ensure_audit_table(engine)
        d   = _dialect(engine)
        tbl = _tbl(d)
        now = _now(d)
        with engine.begin() as con:
            con.execute(text(f"""
                INSERT INTO {tbl}
                (AUDIT_ID,EVENT_TIME,EVENT_TYPE,USER_ID,USER_NAME,
                 TARGET_ID,TARGET_TYPE,TARGET_NAME,
                 OLD_VALUE,NEW_VALUE,NOTES,SESSION_ID)
                VALUES(:aid,{now},:et,:uid,:un,
                       :tid,:tt,:tn,:ov,:nv,:notes,:sid)
            """), {
                "aid":  uuid.uuid4().hex[:40].upper(),
                "et":   str(event_type)[:50],
                "uid":  str(user_id)[:40],
                "un":   str(user_name)[:255],
                "tid":  str(target_id)[:40],
                "tt":   str(target_type)[:50],
                "tn":   str(target_name)[:500],
                "ov":   json.dumps(old_value) if old_value is not None else None,
                "nv":   json.dumps(new_value) if new_value is not None else None,
                "notes":str(notes)[:1000],
                "sid":  str(session_id)[:40],
            })
    except Exception:
        pass


def get_recent(engine, days=30, event_type=None, user_id=None, limit=1000):
    try:
        ensure_audit_table(engine)
        d   = _dialect(engine)
        tbl = _tbl(d)
        now = _now(d)

        # Dialect-specific date filter
        if d == "oracle":
            date_filter = f"EVENT_TIME >= {now} - {abs(days)}"
        elif d == "snowflake":
            date_filter = f"EVENT_TIME >= DATEADD('day',{-abs(days)},{now})"
        else:
            date_filter = f"EVENT_TIME >= DATEADD(day,{-abs(days)},{now})"

        where  = [date_filter]
        params = {"limit": limit}
        if event_type:
            where.append("EVENT_TYPE=:et"); params["et"] = event_type
        if user_id:
            where.append("USER_ID=:uid");  params["uid"] = user_id

        where_sql = " AND ".join(where)

        # Dialect-specific limit
        if d == "mssql":
            sql = (f"SELECT TOP(:limit) AUDIT_ID,EVENT_TIME,EVENT_TYPE,"
                   f"USER_NAME,TARGET_TYPE,TARGET_NAME,OLD_VALUE,NEW_VALUE,NOTES "
                   f"FROM {tbl} WHERE {where_sql} ORDER BY EVENT_TIME DESC")
        elif d == "oracle":
            sql = (f"SELECT * FROM ("
                   f"SELECT AUDIT_ID,EVENT_TIME,EVENT_TYPE,"
                   f"USER_NAME,TARGET_TYPE,TARGET_NAME,OLD_VALUE,NEW_VALUE,NOTES "
                   f"FROM {tbl} WHERE {where_sql} ORDER BY EVENT_TIME DESC"
                   f") WHERE ROWNUM <= :limit")
        else:
            sql = (f"SELECT AUDIT_ID,EVENT_TIME,EVENT_TYPE,"
                   f"USER_NAME,TARGET_TYPE,TARGET_NAME,OLD_VALUE,NEW_VALUE,NOTES "
                   f"FROM {tbl} WHERE {where_sql} ORDER BY EVENT_TIME DESC "
                   f"LIMIT :limit")

        with engine.connect() as con:
            rows = con.execute(text(sql), params).fetchall()

        cols = ["audit_id","event_time","event_type","user_name",
                "target_type","target_name","old_value","new_value","notes"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []


# ── Convenience wrappers ──────────────────────────────────────────────────────

def audit_login(engine, user):
    audit(engine, LOGIN, user.get("user_id",""), user.get("full_name",""),
          target_type="SESSION", notes=f"Login — role: {user.get('role','')}")

def audit_logout(engine, user):
    audit(engine, LOGOUT, user.get("user_id",""), user.get("full_name",""),
          target_type="SESSION")

def audit_impersonate(engine, actor, target):
    audit(engine, IMPERSONATE, actor.get("user_id",""), actor.get("full_name",""),
          target_id=target.get("user_id",""), target_type="USER",
          target_name=target.get("full_name",""),
          notes=f"Impersonating {target.get('full_name','')} ({target.get('role','')})")

def audit_impersonate_exit(engine, actor, was):
    audit(engine, IMPERSONATE_EXIT, actor.get("user_id",""), actor.get("full_name",""),
          target_id=was.get("user_id",""), target_type="USER",
          target_name=was.get("full_name",""),
          notes=f"Exited impersonation of {was.get('full_name','')}")

def audit_catalog(engine, user, file_name, file_format, file_id="", action=""):
    audit(engine, CATALOG, user.get("user_id",""), user.get("full_name",""),
          target_id=file_id, target_type="FILE", target_name=file_name,
          notes=f"{file_format} — {action}" if action else file_format)

def audit_skip(engine, user, file_name, reason=""):
    audit(engine, SKIP, user.get("user_id",""), user.get("full_name",""),
          target_type="FILE", target_name=file_name, notes=reason)

def audit_assign(engine, user, group_name, assignment_id, cataloger_name, file_count):
    audit(engine, ASSIGN, user.get("user_id",""), user.get("full_name",""),
          target_id=assignment_id, target_type="ASSIGNMENT", target_name=group_name,
          notes=f"Assigned {file_count:,} files to {cataloger_name}")

def audit_reassign(engine, user, assignment_id, group_name, from_name, to_name):
    audit(engine, REASSIGN, user.get("user_id",""), user.get("full_name",""),
          target_id=assignment_id, target_type="ASSIGNMENT", target_name=group_name,
          old_value={"cataloger": from_name}, new_value={"cataloger": to_name})

def audit_remove_assign(engine, user, assignment_id, group_name, file_count):
    audit(engine, REMOVE_ASSIGN, user.get("user_id",""), user.get("full_name",""),
          target_id=assignment_id, target_type="ASSIGNMENT", target_name=group_name,
          notes=f"{file_count:,} files returned to pool")

def audit_password_reset(engine, actor, target_name, target_id):
    audit(engine, PASSWORD_RESET, actor.get("user_id",""), actor.get("full_name",""),
          target_id=target_id, target_type="USER", target_name=target_name)

def audit_password_change(engine, user):
    audit(engine, PASSWORD_CHANGE, user.get("user_id",""), user.get("full_name",""),
          target_type="USER", target_name=user.get("full_name",""))

def audit_export(engine, user, export_type, row_count):
    audit(engine, EXPORT, user.get("user_id",""), user.get("full_name",""),
          target_type="EXPORT", target_name=export_type,
          notes=f"{row_count:,} rows exported")

def audit_ppdm_update(engine, user, table, row_count, batch_id=""):
    audit(engine, PPDM_UPDATE, user.get("user_id",""), user.get("full_name",""),
          target_type="PPDM", target_name=table, target_id=batch_id,
          notes=f"{row_count:,} rows applied to {table}")

def audit_user_create(engine, actor, new_name, new_id, role):
    audit(engine, USER_CREATE, actor.get("user_id",""), actor.get("full_name",""),
          target_id=new_id, target_type="USER", target_name=new_name,
          notes=f"Role: {role}")

def audit_user_deactivate(engine, actor, target_name, target_id, active):
    audit(engine, USER_DEACTIVATE, actor.get("user_id",""), actor.get("full_name",""),
          target_id=target_id, target_type="USER", target_name=target_name,
          notes="Activated" if active else "Deactivated")

def audit_user_delete(engine, actor, target_name, target_id):
    audit(engine, USER_DELETE, actor.get("user_id",""), actor.get("full_name",""),
          target_id=target_id, target_type="USER", target_name=target_name)

def audit_crawl(engine, user, repo_name, file_count, dup_count=0):
    audit(engine, CRAWL, user.get("user_id",""), user.get("full_name",""),
          target_type="REPOSITORY", target_name=repo_name,
          notes=f"{file_count:,} files found, {dup_count:,} duplicates")

def audit_clear(engine, user, what):
    audit(engine, CLEAR, user.get("user_id",""), user.get("full_name",""),
          target_type="DATA", target_name=what, notes=f"Cleared: {what}")
