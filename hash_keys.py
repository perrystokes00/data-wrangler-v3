"""
hash_keys.py  —  DataView v3 · Canonical entity-ID hashing
==========================================================
SINGLE SOURCE OF TRUTH for deriving SHA-1 entity IDs
(ba_id, field_id, contractor_id, pool_id, ...).

Every system that writes OR resolves a SHA-1 entity key MUST import
from here:  entity_seeder.py, fk_entity.py, fk.py, page_pipeline.py.
Do not redefine the recipe anywhere else.

THE RECIPE (and why it is the only valid one):
    SQL Server stores entity IDs by computing them server-side via
        CONVERT(CHAR(40), HASHBYTES('SHA1', UPPER(TRIM(@name))), 2)
    HASHBYTES on an nvarchar hashes the UTF-16-LE bytes; CONVERT(...,2)
    emits UPPERCASE hex. The ONLY Python recipe that can ever agree with
    that is: UPPER+TRIM the string, encode UTF-16-LE, sha1, uppercase hex.

    Any UTF-8 / lowercase / no-UPPER variant produces a different digest
    for the SAME name and will silently orphan every FK. (This was the
    DataView_Demo operator-FK failure: entity_seeder used UTF-8/lowercase/
    no-UPPER while the pipeline used this recipe.)

NOTE ON TRIM:
    Python str.strip() removes all leading/trailing Unicode whitespace
    (incl. tab/CR/LF). SQL Server TRIM() (default) removes spaces only.
    For names whose only padding is spaces, Python and server agree.
    For names padded with tab/CR/LF, the server-computed ID and a
    Python-computed ID can diverge. normalise_for_sha1() therefore
    strips ALL whitespace edges to match str.strip(); if you also want
    the server side to agree on tab/CR/LF padding, have the SQL UPPER/TRIM
    expression scrub those (see SQL_TRIM_EXPR below) instead of bare TRIM().
"""
from __future__ import annotations

import hashlib

# Encoding per dialect. SQL Server HASHBYTES(nvarchar) == UTF-16-LE.
SQLSERVER_ENCODING = "utf-16-le"
ORACLE_ENCODING    = "utf-8"   # UTL_RAW.CAST_TO_RAW on the DB charset


def normalise_for_sha1(value: str) -> str:
    """
    Canonical normalisation prior to hashing: UPPER + strip().
    Mirrors SQL UPPER(TRIM(...)). str.strip() also removes tab/CR/LF so
    that names with non-space edge padding still hash deterministically.
    """
    if value is None:
        return ""
    return value.upper().strip()


def sha1_hex(value: str, encoding: str = SQLSERVER_ENCODING) -> str:
    """
    SHA-1 hex of an ALREADY-normalised string.
    Returns 40-char UPPERCASE hex. Pass the output of normalise_for_sha1().
    """
    return hashlib.sha1(value.encode(encoding)).hexdigest().upper()


def entity_id(name: str, encoding: str = SQLSERVER_ENCODING) -> str | None:
    """
    Convenience one-shot: raw name -> canonical 40-char uppercase ID.
    Returns None for empty/whitespace-only names so callers can skip them
    instead of inserting a hash of "".
    """
    norm = normalise_for_sha1(name)
    if not norm:
        return None
    return sha1_hex(norm, encoding)


# SQL Server expression that produces the IDENTICAL id server-side.
# Use this in HASHBYTES inserts / promote UPDATEs so the server-computed
# id matches entity_id() above. Scrubs tab/CR/LF as well as spaces.
def sql_normalise_expr(col_or_literal: str, is_col: bool = True) -> str:
    inner = f"[{col_or_literal}]" if is_col else f"'{col_or_literal}'"
    # strip tab(9)/CR(13)/LF(10) edges, then UPPER+TRIM spaces
    scrub = (
        f"REPLACE(REPLACE(REPLACE({inner}, CHAR(9), ''), "
        f"CHAR(13), ''), CHAR(10), '')"
    )
    return f"UPPER(LTRIM(RTRIM({scrub})))"


def sql_sha1_expr(col_or_literal: str, is_col: bool = True) -> str:
    """
    Full SQL Server SHA-1 expression matching entity_id():
        CONVERT(CHAR(40), HASHBYTES('SHA1', UPPER(TRIM(scrub(x)))), 2)
    """
    norm = sql_normalise_expr(col_or_literal, is_col)
    return f"CONVERT(CHAR(40), HASHBYTES('SHA1', {norm}), 2)"


if __name__ == "__main__":
    # Sanity: same name, both encodings, and a punctuation/case/space mix.
    for raw in ["Smith & Sons, LLC", "  smith & SONS, llc  ", "EOG RESOURCES"]:
        print(f"{raw!r:32} -> {entity_id(raw)}")
    # First two MUST collide (case/space-insensitive); they do NOT strip
    # punctuation, so '&' and ',' are part of the identity. Confirm that
    # matches what dv_business_associate expects before bulk re-seeding.
