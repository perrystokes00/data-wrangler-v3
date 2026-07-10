"""
classify_inventory.py
====================
Inventory enrichment stage: tag every DOCUMENT row in
file_catalog.GLOBAL_FILE_CATALOG with a DOC_TYPE + DOC_TYPE_SCORE, using the
example-driven DocClassifier. Runs after the scan crawl (which already built the
corpus) and before deep extract, so DOC_TYPE can drive both the cataloger work
queue and extractor routing.

Design notes
------------
* DOCUMENTS ONLY. Embeddings judge ambiguous documents (pdf/docx/txt/...). Data
  files (LAS/SEG-Y/DLIS) are typed deterministically by extension elsewhere and
  are skipped here — we never embed a seismic volume.
* DEDUP BY HASH. The crawl already groups identical content via DUPLICATE_GROUP.
  We classify ONE representative per group, then propagate the label to its
  duplicates — so a 500k-file vault classifies distinct content once.
* SET-BASED WRITE-BACK. Results land via a staging temp + JOIN UPDATE, never a
  per-row UPDATE loop (SQL-Express doctrine).
* Text reads happen on the engine host (FILE_PATH on local disk).

Usage
-----
    from sqlalchemy import create_engine
    from classify_inventory import run
    run(engine, r"C:\\Bulk\\doc_type_examples")          # classify new docs
    run(engine, r"C:\\Bulk\\doc_type_examples", reclassify=True)  # re-do all
"""
from __future__ import annotations

from doc_classifier import DocClassifier, load_examples, sample_text, DOC_TEXT_EXTS

CAT = "file_catalog.GLOBAL_FILE_CATALOG"


def _ensure_classify_cols(engine):
    from sqlalchemy import text as _t
    with engine.begin() as con:
        con.execute(_t(
            "IF COL_LENGTH('file_catalog.GLOBAL_FILE_CATALOG','DOC_TYPE') IS NULL "
            "ALTER TABLE file_catalog.GLOBAL_FILE_CATALOG ADD DOC_TYPE NVARCHAR(80) NULL;"))
        con.execute(_t(
            "IF COL_LENGTH('file_catalog.GLOBAL_FILE_CATALOG','DOC_TYPE_SCORE') IS NULL "
            "ALTER TABLE file_catalog.GLOBAL_FILE_CATALOG ADD DOC_TYPE_SCORE FLOAT NULL;"))
        con.execute(_t(
            "IF COL_LENGTH('file_catalog.GLOBAL_FILE_CATALOG','DOC_TYPE_AT') IS NULL "
            "ALTER TABLE file_catalog.GLOBAL_FILE_CATALOG ADD DOC_TYPE_AT DATETIME2 NULL;"))


def _ext_in_clause(exts):
    vals = ", ".join("'" + e.replace("'", "") + "'" for e in sorted(exts))
    return f"LOWER(g.FILE_EXT) IN ({vals})"


def _fetch_candidates(con, reclassify: bool, limit):
    """One representative document row per DUPLICATE_GROUP (plus ungrouped rows)
    that still needs a DOC_TYPE. Returns list of (inventory_id, dup_group, path)."""
    from sqlalchemy import text as _t
    top = f"TOP {int(limit)} " if limit else ""
    where_new = "" if reclassify else "AND g.DOC_TYPE IS NULL"
    sql = f"""
        SELECT {top}g.INVENTORY_ID, g.DUPLICATE_GROUP, g.FILE_PATH
          FROM (
            SELECT g.*,
                   ROW_NUMBER() OVER (
                     PARTITION BY COALESCE(CONVERT(NVARCHAR(80), g.DUPLICATE_GROUP),
                                           CONVERT(NVARCHAR(80), g.INVENTORY_ID))
                     ORDER BY g.INVENTORY_ID) AS _rn
              FROM {CAT} g
             WHERE {_ext_in_clause(DOC_TEXT_EXTS)}
               AND ISNULL(g.FLAG_DELETE, 'N') <> 'Y'
               {where_new}
          ) g
         WHERE g._rn = 1
    """
    rows = con.execute(_t(sql)).fetchall()
    return [(r.INVENTORY_ID, r.DUPLICATE_GROUP, r.FILE_PATH) for r in rows]


def _write_back(engine, results, log):
    """results: list of dicts {inv, grp, doc_type, score}. Staging temp + JOIN:
    update the classified reps, then propagate each label across its dup group."""
    from sqlalchemy import text as _t
    if not results:
        return 0
    with engine.begin() as con:
        con.execute(_t("IF OBJECT_ID('tempdb..#cls') IS NOT NULL DROP TABLE #cls;"))
        con.execute(_t(
            "CREATE TABLE #cls (INVENTORY_ID NVARCHAR(80), DUP_GROUP NVARCHAR(80), "
            "DOC_TYPE NVARCHAR(80), SCORE FLOAT);"))
        ins = _t("INSERT INTO #cls (INVENTORY_ID, DUP_GROUP, DOC_TYPE, SCORE) "
                 "VALUES (:inv, :grp, :dt, :sc)")
        con.execute(ins, [{"inv": str(r["inv"]),
                           "grp": (str(r["grp"]) if r["grp"] is not None else None),
                           "dt": r["doc_type"], "sc": r["score"]} for r in results])

        # reps — match by INVENTORY_ID
        con.execute(_t(f"""
            UPDATE g SET g.DOC_TYPE = c.DOC_TYPE, g.DOC_TYPE_SCORE = c.SCORE,
                         g.DOC_TYPE_AT = SYSUTCDATETIME()
              FROM {CAT} g
              JOIN #cls c ON CONVERT(NVARCHAR(80), g.INVENTORY_ID) = c.INVENTORY_ID;"""))

        # propagate to duplicates that share the group and aren't set yet
        n = con.execute(_t(f"""
            UPDATE g SET g.DOC_TYPE = c.DOC_TYPE, g.DOC_TYPE_SCORE = c.SCORE,
                         g.DOC_TYPE_AT = SYSUTCDATETIME()
              FROM {CAT} g
              JOIN #cls c ON c.DUP_GROUP IS NOT NULL
                         AND CONVERT(NVARCHAR(80), g.DUPLICATE_GROUP) = c.DUP_GROUP
             WHERE g.DOC_TYPE IS NULL;""")).rowcount
        con.execute(_t("DROP TABLE #cls;"))
    return len(results) + (n if n and n > 0 else 0)


def run(engine, examples_dir: str, *, reclassify: bool = False, dry: bool = False,
        limit=None, chunk: int = 400, log=print) -> dict:
    """Classify document rows in GLOBAL_FILE_CATALOG and write DOC_TYPE back.
    dry=True classifies and prints results without writing anything."""
    examples = load_examples(examples_dir)
    if not examples:
        log(f"[classify] no examples found under {examples_dir} — nothing to do")
        return {"types": 0, "classified": 0}
    clf = DocClassifier(examples)
    log(f"[classify] backend={clf.backend}  types={len(clf.types)}: {', '.join(clf.types)}")

    _ensure_classify_cols(engine)
    with engine.connect() as con:
        cands = _fetch_candidates(con, reclassify, limit)
    log(f"[classify] {len(cands):,} distinct document(s) to classify"
        f"{' (DRY RUN)' if dry else ''}")

    results, tally = [], {}
    for i in range(0, len(cands), chunk):
        batch = cands[i:i + chunk]
        corpus, meta = {}, {}
        for inv, grp, path in batch:
            corpus[str(inv)] = sample_text(path)
            meta[str(inv)] = (inv, grp, path)
        labels, thr = clf.classify_batch(corpus)
        for k, (dt, sc) in labels.items():
            inv, grp, path = meta[k]
            results.append({"inv": inv, "grp": grp, "path": path,
                            "doc_type": dt, "score": sc})
            tally[dt] = tally.get(dt, 0) + 1
        log(f"[classify] {min(i+chunk, len(cands)):,}/{len(cands):,} "
            f"(threshold {thr})")

    if dry:
        import os as _os
        log("\n[classify] DRY RUN — per-file results (nothing written):")
        for r in sorted(results, key=lambda x: (x["doc_type"], -x["score"])):
            log(f"    {r['score']:>6}  {r['doc_type']:24} {_os.path.basename(r['path'])}")
        written = 0
    else:
        written = _write_back(engine, results, log)

    log("")
    for t in sorted(tally, key=lambda x: -tally[x]):
        log(f"[classify]   {t:24} {tally[t]:>6}")
    log(f"[classify] {'would tag' if dry else 'done —'} {len(results):,} file(s) "
        f"({tally.get('REVIEW', 0):,} REVIEW)"
        f"{'' if dry else f' · {written:,} row(s) written'}")
    return {"types": len(clf.types), "classified": (0 if dry else written),
            "tally": tally, "dry": dry}
