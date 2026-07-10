"""Shared file fingerprinting + duplicate-grouping — the single source of truth
for both scan paths (pipeline_run / page_workbench AND modules.file_inventory).

Keeping ONE implementation here means the two scanners always write the same
FILE_HASH and group duplicates identically, so a file scanned by either path is
deduped the same way. Stdlib only (os, hashlib) — no DB, no Streamlit — so it is
safe to import from anywhere, including spawned process-pool workers.
"""

import hashlib
import os

# FILE_HASH is varchar(40+) in GLOBAL_FILE_CATALOG, so SHA-1 (40 hex) fits.
# Files <= FULL_MAX are hashed in full; larger files use a cheap composite
# (size + leading/trailing edge) so a scan never streams gigabytes of seismic.
# Deterministic per file: two identical files take the same branch (same size)
# and hash identically, so duplicate grouping still matches.
HASH_FULL_MAX = 16 * 1024 * 1024      # 16 MB
_HASH_EDGE    = 1 * 1024 * 1024       # 1 MB head + 1 MB tail for big files


def file_fingerprint(path: str, size_bytes: int, mtime: float = 0.0) -> str:
    """SHA-1 content fingerprint, 40-char uppercase hex.

    Small files (<= HASH_FULL_MAX) are hashed in full; large files hash
    size + 1 MB head + 1 MB tail. Falls back to size+mtime if the bytes can't be
    read (locked / online-only), so every file still gets a non-empty key.
    Returns '' only if even the stat fallback fails.
    """
    h = hashlib.sha1()
    try:
        if size_bytes <= HASH_FULL_MAX:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        else:
            h.update(f"{size_bytes}|".encode())
            with open(path, "rb") as f:
                h.update(f.read(_HASH_EDGE))          # head
                if size_bytes > _HASH_EDGE:
                    f.seek(-_HASH_EDGE, os.SEEK_END)
                    h.update(f.read(_HASH_EDGE))      # tail
        return h.hexdigest().upper()
    except OSError:
        try:
            h.update(f"{size_bytes}|{mtime}".encode())
            return h.hexdigest().upper()
        except Exception:
            return ""


# ── Duplicate grouping (SQL Server) ──────────────────────────────────────────
# One canonical kept per FILE_HASH (DUPLICATE_GROUP stays NULL); every redundant
# copy gets DUPLICATE_GROUP = its FILE_HASH. Canonical preference: an already
# CATALOGED row wins (so we never flag a finished file as the dup), else the
# lexicographically smallest INVENTORY_ID — deterministic. Full recompute each
# call (clear, then re-mark from the whole table), so it is idempotent across
# re-scans: a copy whose twin was deleted reverts to NULL automatically.
#
# Consumers (assignment, extract, capture) all gate on `DUPLICATE_GROUP IS NULL`
# = "the one representative to process"; rows with it set are the skippable
# redundant copies.
DEDUPE_SQL = """
UPDATE file_catalog.GLOBAL_FILE_CATALOG
   SET DUPLICATE_GROUP = NULL
 WHERE DUPLICATE_GROUP IS NOT NULL;

WITH grp AS (
    SELECT INVENTORY_ID,
           ROW_NUMBER() OVER (
               PARTITION BY FILE_HASH
               ORDER BY CASE WHEN ISNULL(CATALOG_STATUS, '') = 'CATALOGED'
                             THEN 0 ELSE 1 END,
                        INVENTORY_ID) AS rn
      FROM file_catalog.GLOBAL_FILE_CATALOG
     WHERE FILE_HASH IS NOT NULL AND FILE_HASH <> ''
)
UPDATE t
   SET t.DUPLICATE_GROUP = t.FILE_HASH
  FROM file_catalog.GLOBAL_FILE_CATALOG t
  JOIN grp ON grp.INVENTORY_ID = t.INVENTORY_ID
 WHERE grp.rn > 1;
"""
