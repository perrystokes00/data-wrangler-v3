"""
modules/file_inventory.py  —  Data Wrangler Global File Inventory
==================================================================
Crawls one or more root paths, hashes files, detects duplicates,
and cross-references against the las_catalog / seis_catalog tables
to show cataloging progress.

Supports SQL Server, Oracle and Snowflake via dialect-aware DDL.
Schema: file_catalog
Table:  file_catalog.GLOBAL_FILE_CATALOG
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

INVENTORY_SCHEMA = "file_catalog"
INVENTORY_TABLE  = "GLOBAL_FILE_CATALOG"

FILE_TYPE_GROUPS = {
    "Well Logs":   [".las", ".dlis", ".dis", ".lis"],
    "Seismic":     [".segy", ".sgy", ".seg", ".p190", ".p90", ".p1"],
    "Spatial":     [".shp", ".geojson", ".gdb", ".kml", ".kmz"],
    "Data":        [".csv", ".xlsx", ".xls"],
    "Documents":   [".pdf", ".docx", ".doc"],
}

ALL_EXTENSIONS = sorted({
    ext for exts in FILE_TYPE_GROUPS.values() for ext in exts
})

HASH_CHUNK_BYTES = 65536   # 64 KB


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _make_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:40].upper()


def _fast_hash(path: str) -> str:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            h.update(f.read(HASH_CHUNK_BYTES))
    except Exception:
        pass
    return h.hexdigest().upper()


def _full_hash(path: str) -> str:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(HASH_CHUNK_BYTES), b""):
                h.update(chunk)
    except Exception:
        pass
    return h.hexdigest().upper()


def _detect_dialect(engine) -> str:
    try:
        name = engine.dialect.name.lower()
        if "oracle" in name:
            return "oracle"
        if "snowflake" in name:
            return "snowflake"
    except Exception:
        pass
    return "sqlserver"


def _ext_to_group(ext: str) -> str:
    ext = ext.lower()
    for group, exts in FILE_TYPE_GROUPS.items():
        if ext in exts:
            return group
    return "Other"


# ── DDL ───────────────────────────────────────────────────────────────────────

def _ddl_create_schema(dialect: str) -> str | None:
    if dialect == "sqlserver":
        return (
            "IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'file_catalog') "
            "EXEC('CREATE SCHEMA [file_catalog]')"
        )
    return None


def _ddl_table_exists(dialect: str) -> str:
    if dialect == "oracle":
        return ("SELECT COUNT(*) FROM ALL_TABLES "
                "WHERE TABLE_NAME = 'GLOBAL_FILE_CATALOG'")
    if dialect == "snowflake":
        return ("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_NAME = 'GLOBAL_FILE_CATALOG'")
    return ("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = 'file_catalog' "
            "AND TABLE_NAME = 'GLOBAL_FILE_CATALOG'")


def _ddl_create_table(dialect: str) -> str:
    if dialect == "oracle":
        return """
            CREATE TABLE GLOBAL_FILE_CATALOG (
                INVENTORY_ID      VARCHAR2(40)    NOT NULL,
                FILE_PATH         VARCHAR2(1000)  NOT NULL,
                FILE_NAME         VARCHAR2(500)   NOT NULL,
                FILE_EXT          VARCHAR2(20),
                FILE_SIZE_KB      NUMBER(15,2),
                FILE_HASH         VARCHAR2(64),
                FILE_HASH_FULL    VARCHAR2(64),
                DUPLICATE_GROUP   VARCHAR2(64),
                MODIFIED_DATE     TIMESTAMP,
                SCAN_DATE         TIMESTAMP       NOT NULL,
                CATALOG_STATUS    VARCHAR2(20),
                CATALOG_TABLE     VARCHAR2(100),
                ROOT_PATH         VARCHAR2(500),
                FILE_TYPE_GROUP   VARCHAR2(50),
                ROW_CREATED_DATE  TIMESTAMP       NOT NULL,
                ROW_CHANGED_DATE  TIMESTAMP       NOT NULL,
                CONSTRAINT PK_GLOBAL_FILE_CATALOG PRIMARY KEY (INVENTORY_ID)
            )"""
    if dialect == "snowflake":
        return """
            CREATE TABLE GLOBAL_FILE_CATALOG (
                INVENTORY_ID      VARCHAR(40)     NOT NULL,
                FILE_PATH         VARCHAR(1000)   NOT NULL,
                FILE_NAME         VARCHAR(500)    NOT NULL,
                FILE_EXT          VARCHAR(20),
                FILE_SIZE_KB      NUMERIC(15,2),
                FILE_HASH         VARCHAR(64),
                FILE_HASH_FULL    VARCHAR(64),
                DUPLICATE_GROUP   VARCHAR(64),
                MODIFIED_DATE     TIMESTAMP_NTZ,
                SCAN_DATE         TIMESTAMP_NTZ   NOT NULL,
                CATALOG_STATUS    VARCHAR(20),
                CATALOG_TABLE     VARCHAR(100),
                ROOT_PATH         VARCHAR(500),
                FILE_TYPE_GROUP   VARCHAR(50),
                ROW_CREATED_DATE  TIMESTAMP_NTZ   NOT NULL,
                ROW_CHANGED_DATE  TIMESTAMP_NTZ   NOT NULL,
                PRIMARY KEY (INVENTORY_ID)
            )"""
    return """
        CREATE TABLE [file_catalog].[GLOBAL_FILE_CATALOG] (
            [INVENTORY_ID]      NVARCHAR(40)    NOT NULL,
            [FILE_PATH]         NVARCHAR(1000)  NOT NULL,
            [FILE_NAME]         NVARCHAR(500)   NOT NULL,
            [FILE_EXT]          NVARCHAR(20)    NULL,
            [FILE_SIZE_KB]      NUMERIC(15,2)   NULL,
            [FILE_HASH]         NVARCHAR(64)    NULL,
            [FILE_HASH_FULL]    NVARCHAR(64)    NULL,
            [DUPLICATE_GROUP]   NVARCHAR(64)    NULL,
            [MODIFIED_DATE]     DATETIME2       NULL,
            [SCAN_DATE]         DATETIME2       NOT NULL,
            [CATALOG_STATUS]    NVARCHAR(20)    NULL,
            [CATALOG_TABLE]     NVARCHAR(100)   NULL,
            [ROOT_PATH]         NVARCHAR(500)   NULL,
            [FILE_TYPE_GROUP]   NVARCHAR(50)    NULL,
            [ROW_CREATED_DATE]  DATETIME2       NOT NULL,
            [ROW_CHANGED_DATE]  DATETIME2       NOT NULL,
            CONSTRAINT [PK_GLOBAL_FILE_CATALOG] PRIMARY KEY ([INVENTORY_ID])
        )"""


def _ddl_indexes(dialect: str) -> list[str]:
    """
    Indexes on GLOBAL_FILE_CATALOG covering the main query patterns:
      - Browse/assign: LOWER(FILE_EXT), CATALOG_STATUS, ROOT_PATH, IS_DUPLICATE
      - Duplicate detection: FILE_HASH
      - Assignment joins: INVENTORY_ID (PK — already indexed)
      - Type grouping: FILE_TYPE_GROUP
    """
    if dialect == "sqlserver":
        def _ix(name, cols, where=""):
            w = f" WHERE {where}" if where else ""
            return (
                f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='{name}')"
                f" CREATE INDEX [{name}] ON [file_catalog].[GLOBAL_FILE_CATALOG] ({cols}){w}"
            )
        return [
            _ix("GFC_EXT_IDX",    "[FILE_EXT]"),
            _ix("GFC_STATUS_IDX", "[CATALOG_STATUS]"),
            _ix("GFC_ROOT_IDX",   "[ROOT_PATH]"),
            _ix("GFC_HASH_IDX",   "[FILE_HASH]", "[FILE_HASH] IS NOT NULL"),
            _ix("GFC_DUP_IDX",    "[DUPLICATE_GROUP]"),
            _ix("GFC_GROUP_IDX",  "[FILE_TYPE_GROUP]"),
            # Composite covering index for the main assign query
            _ix("GFC_ASSIGN_IDX", "[CATALOG_STATUS],[FILE_TYPE_GROUP],[FILE_EXT],[FILE_NAME],[INVENTORY_ID]"),
        ]
    elif dialect == "oracle":
        def _ix(name, cols):
            return (
                f"DECLARE BEGIN "
                f"EXECUTE IMMEDIATE 'CREATE INDEX {name} ON GLOBAL_FILE_CATALOG ({cols})'; "
                f"EXCEPTION WHEN OTHERS THEN NULL; END;"
            )
        return [
            _ix("GFC_EXT_IDX",    "FILE_EXT"),
            _ix("GFC_STATUS_IDX", "CATALOG_STATUS"),
            _ix("GFC_ROOT_IDX",   "ROOT_PATH"),
            _ix("GFC_HASH_IDX",   "FILE_HASH"),
            _ix("GFC_DUP_IDX",    "DUPLICATE_GROUP"),
            _ix("GFC_GROUP_IDX",  "FILE_TYPE_GROUP"),
            _ix("GFC_ASSIGN_IDX", "CATALOG_STATUS,FILE_TYPE_GROUP,FILE_EXT,FILE_NAME,INVENTORY_ID"),
        ]
    elif dialect == "snowflake":
        # Snowflake uses micro-partitioning — explicit indexes not supported.
        # Cluster keys on the most selective columns improve pruning.
        return [
            'ALTER TABLE "FILE_CATALOG"."GLOBAL_FILE_CATALOG" '
            'CLUSTER BY (CATALOG_STATUS, FILE_TYPE_GROUP, FILE_EXT)',
        ]
    return []


# ── Schema creation ───────────────────────────────────────────────────────────

def ensure_inventory_schema(engine, dialect=None) -> list[str]:  # dialect ignored — auto-detected
    """Create file_catalog schema and GLOBAL_FILE_CATALOG if not present."""
    from sqlalchemy import text
    dialect = _detect_dialect(engine)
    created = []

    with engine.begin() as con:
        schema_ddl = _ddl_create_schema(dialect)
        if schema_ddl:
            con.execute(text(schema_ddl))

        exists = con.execute(text(_ddl_table_exists(dialect))).scalar()
        if not exists:
            con.execute(text(_ddl_create_table(dialect)))
            created.append("GLOBAL_FILE_CATALOG")

        for idx_sql in _ddl_indexes(dialect):
            try:
                con.execute(text(idx_sql))
            except Exception:
                pass

    return created


# ── Catalog cross-reference ───────────────────────────────────────────────────

def _get_cataloged_paths(engine) -> dict[str, str]:
    """Return {normalised_upper_path: catalog_table} for all cataloged files."""
    from sqlalchemy import text
    dialect  = _detect_dialect(engine)
    cataloged: dict[str, str] = {}

    if dialect == "sqlserver":
        queries = [
            ("WL_FILE_CATALOG",
             "SELECT FULL_PATH FROM [las_catalog].[WL_FILE_CATALOG]"),
            ("SEIS_FILE_CATALOG",
             "SELECT FULL_PATH FROM [las_catalog].[SEIS_FILE_CATALOG]"),
        ]
    elif dialect == "oracle":
        queries = [
            ("WL_FILE_CATALOG",   "SELECT FULL_PATH FROM WL_FILE_CATALOG"),
            ("SEIS_FILE_CATALOG", "SELECT FULL_PATH FROM SEIS_FILE_CATALOG"),
        ]
    else:
        queries = [
            ("WL_FILE_CATALOG",   'SELECT FULL_PATH FROM "WL_FILE_CATALOG"'),
            ("SEIS_FILE_CATALOG", 'SELECT FULL_PATH FROM "SEIS_FILE_CATALOG"'),
        ]

    with engine.connect() as con:
        for tbl_name, sql in queries:
            try:
                for row in con.execute(text(sql)).fetchall():
                    if row[0]:
                        cataloged[str(row[0]).upper()] = tbl_name
            except Exception:
                pass
    return cataloged


# ── File scanning ─────────────────────────────────────────────────────────────

def _scan_file(file_path: Path, root_path: str,
               cataloged: dict[str, str],
               full_hash: bool,
               hash_status: dict | None = None) -> dict:
    now = _now_str()
    try:
        stat    = file_path.stat()
        size_kb = round(stat.st_size / 1024, 2)
        mod_dt  = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        size_kb = None
        mod_dt  = None

    path_str  = str(file_path)
    inv_id    = _make_id(path_str)
    ext       = file_path.suffix.lower()
    fast_h    = None
    full_h    = None

    cat_status = "UNCATALOGED"
    cat_table  = None
    if path_str.upper() in cataloged:
        # Path matches a known cataloged file
        cat_status = "CATALOGED"
        cat_table  = cataloged[path_str.upper()]


    return {
        "INVENTORY_ID":     inv_id,
        "FILE_PATH":        path_str,
        "FILE_NAME":        file_path.name,
        "FILE_EXT":         ext,
        "FILE_SIZE_KB":     size_kb,
        "FILE_HASH":        fast_h,
        "FILE_HASH_FULL":   full_h,
        "DUPLICATE_GROUP":  None,
        "MODIFIED_DATE":    mod_dt,
        "SCAN_DATE":        now,
        "CATALOG_STATUS":   cat_status,
        "CATALOG_TABLE":    cat_table,
        "ROOT_PATH":        root_path,
        "FILE_TYPE_GROUP":  _ext_to_group(ext),
        "ROW_CREATED_DATE": now,
        "ROW_CHANGED_DATE": now,
    }


# ── Main crawl entry point ────────────────────────────────────────────────────

def crawl_and_inventory(
    engine,
    root_paths: list[str],
    extensions: list[str],
    full_hash: bool = False,
    max_workers: int = None,
    replace_root: bool = True,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """
    Crawl root_paths for files matching extensions.
    Collects metadata only — no header reading.
    Duplicate detection runs server-side after bulk load — always on, near-instant.

    Returns dict: files_found, files_inserted, duplicates, errors
    """
    from sqlalchemy import text

    if max_workers is None:
        max_workers = max(min((os.cpu_count() or 4) - 1, 8), 2)

    ext_set = {e.lower() for e in extensions}

    import threading, queue, time

    cataloged = _get_cataloged_paths(engine)
    dialect   = _detect_dialect(engine)
    gfc       = ("[file_catalog].[GLOBAL_FILE_CATALOG]" if dialect == "sqlserver"
                 else "GLOBAL_FILE_CATALOG" if dialect == "oracle"
                 else '"FILE_CATALOG"."GLOBAL_FILE_CATALOG"')

    # ── Pre-scan: build two fingerprint lookups ────────────────────────────
    # 1. path_status: INVENTORY_ID -> CATALOG_STATUS for files we already have
    # 2. hash_status: FILE_HASH    -> CATALOG_STATUS for content-based matching
    #    (so a file moved/renamed but with same content is recognised)
    path_status: dict[str, str] = {}   # inventory_id -> CATALOG_STATUS

    try:
        with engine.connect() as con:
            rows = con.execute(text(
                f"SELECT INVENTORY_ID, CATALOG_STATUS FROM {gfc}"
            )).fetchall()
        for inv_id, status in rows:
            path_status[inv_id] = status
    except Exception:
        pass

    # Delete existing rows for these root paths — but only after saving status
    if replace_root:
        with engine.begin() as con:
            for root in root_paths:
                con.execute(text(
                    f"DELETE FROM {gfc} WHERE ROOT_PATH = :r"
                ), {"r": root})

    # ── Stream discovery + scan concurrently ─────────────────────────────────
    # A background thread walks the filesystem and feeds a queue.
    # Worker threads pull from the queue and hash files immediately.
    # The main thread polls counters for progress — no waiting for full discovery.

    _file_queue:  queue.Queue = queue.Queue(maxsize=2000)
    _results:     list[dict]  = []
    errors:       list[str]   = []
    _lock         = threading.Lock()
    _found        = [0]     # files matching extension — discovered
    _done         = [0]     # files hashed and processed
    _folders      = [0]     # folders visited (for discovery phase feedback)
    _last_name    = ["Scanning…"]
    _walk_done    = threading.Event()

    # Folders to skip — case-insensitive
    _SKIP_DIRS = {
        "$recycle.bin", "recycler", "$recycled",
        "system volume information", ".trash", ".trashes",
        "lost+found", "thumbs.db",
    }

    def _walker():
        for root in root_paths:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                # Skip recycle bin and system folders in-place (modifies _dirs)
                _dirs[:] = [d for d in _dirs
                            if d.lower() not in _SKIP_DIRS]
                with _lock:
                    _folders[0] += 1
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in ext_set:
                        fp = Path(os.path.join(dirpath, fname))
                        with _lock:
                            _found[0] += 1
                        _file_queue.put((fp, root))
        _walk_done.set()
        # Poison pills to stop workers
        for _ in range(max_workers):
            _file_queue.put(None)

    def _worker():
        while True:
            item = _file_queue.get()
            if item is None:
                break
            fp, root = item
            try:
                rec = _scan_file(fp, root, cataloged, False, None)
                with _lock:
                    _results.append(rec)
                    _done[0] += 1
                    _last_name[0] = fp.name
            except Exception as e:
                with _lock:
                    errors.append(f"{fp.name}: {e}")
                    _done[0] += 1

    # Start walker thread
    walker_thread = threading.Thread(target=_walker, daemon=True)
    walker_thread.start()

    # Start worker threads
    workers = [
        threading.Thread(target=_worker, daemon=True)
        for _ in range(max_workers)
    ]
    for w in workers:
        w.start()

    # Poll progress on main thread
    # Wait until walker AND all workers are done
    # We track worker completion via a separate counter
    _workers_done = [0]
    _workers_done_lock = threading.Lock()

    def _worker_done_cb():
        with _workers_done_lock:
            _workers_done[0] += 1

    # Patch workers to signal completion — restart with done callback
    # Instead, just poll until walker done AND done==found, with a minimum wait
    while True:
        with _lock:
            found = _found[0]
            done  = _done[0]
            name  = _last_name[0]
            walk_done = _walk_done.is_set()

        if progress_callback:
            with _lock:
                folders = _folders[0]
                name    = _last_name[0]
            if found == 0:
                progress_callback(0, 0, f"Searching… {folders:,} folder(s) scanned")
            else:
                progress_callback(done, found,
                                  f"{folders:,} folders · {name}")

        # Exit when walker finished AND all found files processed
        if walk_done and done >= found:
            break

        time.sleep(0.25)

    # Ensure all threads fully complete before reading results
    walker_thread.join()
    for w in workers:
        w.join()

    with _lock:
        total   = _found[0]
        records = list(_results)

    good = [r for r in records if r is not None]

    # Duplicates detected server-side after bulk load

    # ── UPSERT — preserve catalog status for previously cataloged files ──────
    # If a file already exists (same INVENTORY_ID = same path hash):
    #   UPDATE physical attributes, keep CATALOG_STATUS unchanged
    # If new file: INSERT with status from scan (CATALOGED if hash matched,
    #   UNCATALOGED otherwise)
    from sqlalchemy import text as _text
    from sqlalchemy import text as _text
    # ── Preserve existing catalog status & sanitise ───────────────────────────
    for rec in good:
        existing = path_status.get(rec["INVENTORY_ID"])
        if existing in ("CATALOGED", "SKIPPED"):
            rec["CATALOG_STATUS"] = existing
        for col in ("FILE_PATH","FILE_NAME","FILE_EXT","ROOT_PATH",
                    "FILE_TYPE_GROUP","CATALOG_TABLE"):
            if rec.get(col) is None:
                rec[col] = ""

    inserted = 0

    if not good:
        pass

    elif dialect == "sqlserver":
        # ── Write to local CSV then BULK INSERT — fastest possible ───────────
        import csv, uuid
        COLS = ["INVENTORY_ID","FILE_PATH","FILE_NAME","FILE_EXT",
                "FILE_TYPE_GROUP","FILE_SIZE_KB","FILE_HASH",
                "DUPLICATE_GROUP","CATALOG_STATUS","CATALOG_TABLE",
                "ROOT_PATH","SCAN_DATE","ROW_CREATED_DATE","ROW_CHANGED_DATE"]

        bulk_dir = r"C:\Bulk"
        os.makedirs(bulk_dir, exist_ok=True)
        csv_path = os.path.join(bulk_dir, f"inv_stage_{uuid.uuid4().hex[:8]}.csv")

        try:
            # Write all records to local CSV
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                for rec in good:
                    writer.writerow([
                        rec.get(c, "") if rec.get(c) is not None else ""
                        for c in COLS
                    ])

            with engine.begin() as con:
                # Create staging table
                con.execute(_text("""
                    IF OBJECT_ID('file_catalog.inv_bulk_stage','U') IS NOT NULL
                        DROP TABLE file_catalog.inv_bulk_stage;
                    CREATE TABLE file_catalog.inv_bulk_stage (
                        INVENTORY_ID     NVARCHAR(40),
                        FILE_PATH        NVARCHAR(900),
                        FILE_NAME        NVARCHAR(260),
                        FILE_EXT         NVARCHAR(20),
                        FILE_TYPE_GROUP  NVARCHAR(50),
                        FILE_SIZE_KB     NVARCHAR(30),
                        FILE_HASH        NVARCHAR(40),
                        DUPLICATE_GROUP  NVARCHAR(64),
                        CATALOG_STATUS   NVARCHAR(20),
                        CATALOG_TABLE    NVARCHAR(100),
                        ROOT_PATH        NVARCHAR(900),
                        SCAN_DATE        NVARCHAR(30),
                        ROW_CREATED_DATE NVARCHAR(30),
                        ROW_CHANGED_DATE NVARCHAR(30)
                    );
                """))

                # BULK INSERT from local CSV
                con.execute(_text(f"""
                    BULK INSERT file_catalog.inv_bulk_stage
                    FROM '{csv_path}'
                    WITH (
                        FIELDTERMINATOR = ',',
                        ROWTERMINATOR   = '0x0D0A',
                        CODEPAGE        = '65001',
                        FIRSTROW        = 1,
                        TABLOCK
                    );
                """))

                # Single MERGE from stage → target
                con.execute(_text("""
                    MERGE [file_catalog].[GLOBAL_FILE_CATALOG] AS tgt
                    USING file_catalog.inv_bulk_stage AS src
                    ON tgt.INVENTORY_ID = src.INVENTORY_ID
                    WHEN MATCHED THEN UPDATE SET
                        FILE_SIZE_KB    = TRY_CAST(src.FILE_SIZE_KB AS DECIMAL(15,2)),
                        FILE_HASH       = src.FILE_HASH,
                        DUPLICATE_GROUP = src.DUPLICATE_GROUP,
                        CATALOG_STATUS  = src.CATALOG_STATUS,
                        SCAN_DATE       = TRY_CAST(src.SCAN_DATE AS DATETIME2),
                        ROW_CHANGED_DATE= TRY_CAST(src.ROW_CHANGED_DATE AS DATETIME2)
                    WHEN NOT MATCHED THEN INSERT (
                        INVENTORY_ID,FILE_PATH,FILE_NAME,FILE_EXT,
                        FILE_TYPE_GROUP,FILE_SIZE_KB,FILE_HASH,
                        DUPLICATE_GROUP,CATALOG_STATUS,CATALOG_TABLE,
                        ROOT_PATH,SCAN_DATE,ROW_CREATED_DATE,ROW_CHANGED_DATE
                    ) VALUES (
                        src.INVENTORY_ID,src.FILE_PATH,src.FILE_NAME,src.FILE_EXT,
                        src.FILE_TYPE_GROUP,
                        TRY_CAST(src.FILE_SIZE_KB AS DECIMAL(15,2)),
                        src.FILE_HASH,src.DUPLICATE_GROUP,src.CATALOG_STATUS,
                        src.CATALOG_TABLE,src.ROOT_PATH,
                        TRY_CAST(src.SCAN_DATE AS DATETIME2),
                        TRY_CAST(src.ROW_CREATED_DATE AS DATETIME2),
                        TRY_CAST(src.ROW_CHANGED_DATE AS DATETIME2)
                    );
                """))

                # Server-side duplicate detection
                con.execute(_text("""
                    UPDATE t SET t.DUPLICATE_GROUP = t.FILE_HASH
                    FROM [file_catalog].[GLOBAL_FILE_CATALOG] t
                    INNER JOIN (
                        SELECT FILE_HASH FROM [file_catalog].[GLOBAL_FILE_CATALOG]
                        WHERE FILE_HASH IS NOT NULL AND FILE_HASH != ''
                        GROUP BY FILE_HASH HAVING COUNT(*) > 1
                    ) dups ON t.FILE_HASH = dups.FILE_HASH
                """))

                # Drop staging table
                con.execute(_text(
                    "DROP TABLE IF EXISTS file_catalog.inv_bulk_stage"
                ))

                inserted = len(good)

        except Exception as e:
            errors.append(f"Bulk load error: {e}")
        finally:
            # Always clean up the CSV
            try:
                if os.path.exists(csv_path):
                    os.remove(csv_path)
            except Exception:
                pass
    else:
        # Oracle / Snowflake: per-row MERGE
        for rec in good:
            try:
                with engine.begin() as con:
                    if dialect == "oracle":
                        con.execute(_text("""
                            MERGE INTO GLOBAL_FILE_CATALOG tgt
                            USING (SELECT :INVENTORY_ID AS INVENTORY_ID FROM DUAL) src
                            ON (tgt.INVENTORY_ID = src.INVENTORY_ID)
                            WHEN MATCHED THEN UPDATE SET
                                FILE_SIZE_KB=:FILE_SIZE_KB,FILE_HASH=:FILE_HASH,
                                DUPLICATE_GROUP=:DUPLICATE_GROUP,
                                CATALOG_STATUS=:CATALOG_STATUS,
                                SCAN_DATE=:SCAN_DATE,
                                ROW_CHANGED_DATE=:ROW_CHANGED_DATE
                            WHEN NOT MATCHED THEN INSERT (
                                INVENTORY_ID,FILE_PATH,FILE_NAME,FILE_EXT,
                                FILE_TYPE_GROUP,FILE_SIZE_KB,FILE_HASH,
                                DUPLICATE_GROUP,CATALOG_STATUS,CATALOG_TABLE,
                                ROOT_PATH,SCAN_DATE,ROW_CREATED_DATE,ROW_CHANGED_DATE
                            ) VALUES (
                                :INVENTORY_ID,:FILE_PATH,:FILE_NAME,:FILE_EXT,
                                :FILE_TYPE_GROUP,:FILE_SIZE_KB,:FILE_HASH,
                                :DUPLICATE_GROUP,:CATALOG_STATUS,:CATALOG_TABLE,
                                :ROOT_PATH,:SCAN_DATE,:ROW_CREATED_DATE,
                                :ROW_CHANGED_DATE
                            )
                        """), rec)
                    else:
                        con.execute(_text("""
                            MERGE INTO "FILE_CATALOG"."GLOBAL_FILE_CATALOG" tgt
                            USING (SELECT :INVENTORY_ID AS INVENTORY_ID) src
                            ON tgt."INVENTORY_ID" = src.INVENTORY_ID
                            WHEN MATCHED THEN UPDATE SET
                                "FILE_SIZE_KB"=:FILE_SIZE_KB,
                                "FILE_HASH"=:FILE_HASH,
                                "DUPLICATE_GROUP"=:DUPLICATE_GROUP,
                                "CATALOG_STATUS"=:CATALOG_STATUS,
                                "SCAN_DATE"=:SCAN_DATE,
                                "ROW_CHANGED_DATE"=:ROW_CHANGED_DATE
                            WHEN NOT MATCHED THEN INSERT (
                                "INVENTORY_ID","FILE_PATH","FILE_NAME","FILE_EXT",
                                "FILE_TYPE_GROUP","FILE_SIZE_KB","FILE_HASH",
                                "DUPLICATE_GROUP","CATALOG_STATUS","CATALOG_TABLE",
                                "ROOT_PATH","SCAN_DATE","ROW_CREATED_DATE",
                                "ROW_CHANGED_DATE"
                            ) VALUES (
                                :INVENTORY_ID,:FILE_PATH,:FILE_NAME,:FILE_EXT,
                                :FILE_TYPE_GROUP,:FILE_SIZE_KB,:FILE_HASH,
                                :DUPLICATE_GROUP,:CATALOG_STATUS,:CATALOG_TABLE,
                                :ROOT_PATH,:SCAN_DATE,:ROW_CREATED_DATE,
                                :ROW_CHANGED_DATE
                            )
                        """), rec)
                    inserted += 1
            except Exception as e:
                errors.append(f"{rec.get('FILE_NAME','?')}: {e}")

        # Count duplicates from DB
    dup_count = 0
    try:
            gfc = (f"[file_catalog].[GLOBAL_FILE_CATALOG]" if dialect == "sqlserver"
                   else "GLOBAL_FILE_CATALOG" if dialect == "oracle"
                   else '"FILE_CATALOG"."GLOBAL_FILE_CATALOG"')
            with engine.connect() as con:
                row = con.execute(_text(
                    f"SELECT COUNT(*) FROM {gfc} "
                    f"WHERE DUPLICATE_GROUP IS NOT NULL"
                )).fetchone()
                dup_count = row[0] if row else 0
    except Exception:
        pass

    return {
        "files_found":    total,
        "files_inserted": inserted,
        "duplicates":     dup_count,
        "errors":         errors,
    }


# ── Summary queries ───────────────────────────────────────────────────────────

def get_inventory_summary(engine) -> dict:
    from sqlalchemy import text
    dialect = _detect_dialect(engine)

    if dialect == "sqlserver":
        sql = """
            SELECT COUNT(*), SUM(FILE_SIZE_KB)/1024.0,
                   SUM(CASE WHEN CATALOG_STATUS='CATALOGED'   THEN 1 ELSE 0 END),
                   SUM(CASE WHEN CATALOG_STATUS='UNCATALOGED' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN DUPLICATE_GROUP IS NOT NULL  THEN 1 ELSE 0 END),
                   COUNT(DISTINCT ROOT_PATH)
            FROM [file_catalog].[GLOBAL_FILE_CATALOG]"""
    elif dialect == "oracle":
        sql = """
            SELECT COUNT(*), SUM(FILE_SIZE_KB)/1024,
                   SUM(CASE WHEN CATALOG_STATUS='CATALOGED'   THEN 1 ELSE 0 END),
                   SUM(CASE WHEN CATALOG_STATUS='UNCATALOGED' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN DUPLICATE_GROUP IS NOT NULL  THEN 1 ELSE 0 END),
                   COUNT(DISTINCT ROOT_PATH)
            FROM GLOBAL_FILE_CATALOG"""
    else:
        sql = """
            SELECT COUNT(*), SUM(FILE_SIZE_KB)/1024,
                   SUM(CASE WHEN CATALOG_STATUS='CATALOGED'   THEN 1 ELSE 0 END),
                   SUM(CASE WHEN CATALOG_STATUS='UNCATALOGED' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN DUPLICATE_GROUP IS NOT NULL  THEN 1 ELSE 0 END),
                   COUNT(DISTINCT ROOT_PATH)
            FROM "GLOBAL_FILE_CATALOG" """

    try:
        with engine.connect() as con:
            r = con.execute(text(sql)).fetchone()
        return {
            "total_files":   r[0] or 0,
            "total_size_mb": round(float(r[1] or 0), 1),
            "cataloged":     r[2] or 0,
            "uncataloged":   r[3] or 0,
            "duplicates":    r[4] or 0,
            "root_count":    r[5] or 0,
        }
    except Exception:
        return {"total_files": 0, "total_size_mb": 0, "cataloged": 0,
                "uncataloged": 0, "duplicates": 0, "root_count": 0}


def get_inventory_by_type(engine) -> pd.DataFrame:
    from sqlalchemy import text
    dialect = _detect_dialect(engine)

    if dialect == "sqlserver":
        sql = """
            SELECT FILE_TYPE_GROUP, FILE_EXT, CATALOG_STATUS,
                   COUNT(*) AS file_count, SUM(FILE_SIZE_KB)/1024.0 AS size_mb
            FROM [file_catalog].[GLOBAL_FILE_CATALOG]
            GROUP BY FILE_TYPE_GROUP, FILE_EXT, CATALOG_STATUS
            ORDER BY FILE_TYPE_GROUP, FILE_EXT"""
    elif dialect == "oracle":
        sql = """
            SELECT FILE_TYPE_GROUP, FILE_EXT, CATALOG_STATUS,
                   COUNT(*) AS file_count, SUM(FILE_SIZE_KB)/1024 AS size_mb
            FROM GLOBAL_FILE_CATALOG
            GROUP BY FILE_TYPE_GROUP, FILE_EXT, CATALOG_STATUS
            ORDER BY FILE_TYPE_GROUP, FILE_EXT"""
    else:
        sql = """
            SELECT FILE_TYPE_GROUP, FILE_EXT, CATALOG_STATUS,
                   COUNT(*) AS file_count, SUM(FILE_SIZE_KB)/1024 AS size_mb
            FROM "GLOBAL_FILE_CATALOG"
            GROUP BY FILE_TYPE_GROUP, FILE_EXT, CATALOG_STATUS
            ORDER BY FILE_TYPE_GROUP, FILE_EXT"""

    try:
        with engine.connect() as con:
            rows = con.execute(text(sql)).fetchall()
        return pd.DataFrame(rows, columns=[
            "FILE_TYPE_GROUP", "FILE_EXT", "CATALOG_STATUS",
            "file_count", "size_mb"
        ])
    except Exception:
        return pd.DataFrame()


def get_duplicates(engine) -> pd.DataFrame:
    from sqlalchemy import text
    dialect = _detect_dialect(engine)

    if dialect == "sqlserver":
        sql = """
            SELECT DUPLICATE_GROUP, FILE_NAME, FILE_PATH,
                   FILE_SIZE_KB, FILE_TYPE_GROUP, CATALOG_STATUS
            FROM [file_catalog].[GLOBAL_FILE_CATALOG]
            WHERE DUPLICATE_GROUP IS NOT NULL
            ORDER BY DUPLICATE_GROUP, FILE_PATH"""
    elif dialect == "oracle":
        sql = """
            SELECT DUPLICATE_GROUP, FILE_NAME, FILE_PATH,
                   FILE_SIZE_KB, FILE_TYPE_GROUP, CATALOG_STATUS
            FROM GLOBAL_FILE_CATALOG
            WHERE DUPLICATE_GROUP IS NOT NULL
            ORDER BY DUPLICATE_GROUP, FILE_PATH"""
    else:
        sql = """
            SELECT DUPLICATE_GROUP, FILE_NAME, FILE_PATH,
                   FILE_SIZE_KB, FILE_TYPE_GROUP, CATALOG_STATUS
            FROM "GLOBAL_FILE_CATALOG"
            WHERE DUPLICATE_GROUP IS NOT NULL
            ORDER BY DUPLICATE_GROUP, FILE_PATH"""

    try:
        with engine.connect() as con:
            rows = con.execute(text(sql)).fetchall()
        return pd.DataFrame(rows, columns=[
            "DUPLICATE_GROUP", "FILE_NAME", "FILE_PATH",
            "FILE_SIZE_KB", "FILE_TYPE_GROUP", "CATALOG_STATUS"
        ])
    except Exception:
        return pd.DataFrame()
