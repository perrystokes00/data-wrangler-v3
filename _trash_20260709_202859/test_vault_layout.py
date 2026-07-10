#!/usr/bin/env python3
"""
test_vault_layout.py
====================
Exercise vault_copy.vault()'s folder layout end-to-end **without a database**
and **without touching the real catalog**.

Your real dataset is mostly one-file-per-well, so it never exercises the
interesting paths (a well with several file types, 2D/3D with a year folder,
P190 filed beside its survey).  This harness fabricates a handful of throwaway
dummy files, hands vault() canned catalog rows that point at them through a
fake DBAPI connection, runs the real copy logic, prints the tree it built, and
asserts the expected structure.  Nothing is read from or written to SQL Server.

Run:
    python test_vault_layout.py

Exit code 0 = all checks passed.  Set KEEP=1 in the environment to leave the
built tree on disk for inspection instead of cleaning it up.
"""

import os
import sys
import shutil
import tempfile
import types
from types import SimpleNamespace

# vault_copy imports pyodbc at module load; stub it so this harness needs no DB.
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vault_copy  # noqa: E402


# ── fake DBAPI connection that returns canned rows ──────────────────────────
class _FakeCursor:
    """Recognises the three query shapes vault() issues (table_cols, the wells
    SELECT, the seismic SELECT) and returns canned results.  Any other query —
    e.g. the end-of-run VAULT_FILE bookkeeping — is a harmless no-op."""

    def __init__(self, wells, seis, cols):
        self.rowcount = 0
        self._rows = []
        self._wells = wells
        self._seis = seis
        self._cols = cols  # {"REF":set, "FILE_WELL_HEADER":set, "FILE_SEIS_HEADER":set}

    def execute(self, sql, *args, **kw):
        s = str(sql)
        if "OBJECT_ID(" in s and "c.object_id" in s:
            import re
            m = re.search(r"OBJECT_ID\('([^']+)'\)", s)
            fqtn = (m.group(1) if m else "").upper()
            if "FILE_WELL_HEADER" in fqtn:
                cols = self._cols["FILE_WELL_HEADER"]
            elif "FILE_SEIS_HEADER" in fqtn:
                cols = self._cols["FILE_SEIS_HEADER"]
            else:
                cols = self._cols["REF"]
            self._rows = [(c,) for c in cols]
        elif "file_catalog.FILE_WELL_HEADER h" in s:
            self._rows = list(self._wells)
        elif "file_catalog.FILE_SEIS_HEADER sh" in s:
            self._rows = list(self._seis)
        else:
            self._rows = []  # VAULT_FILE create/stage/merge — ignore
        return self

    def executemany(self, *a, **k):
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    def __init__(self, wells, seis, cols):
        self._cur = _FakeCursor(wells, seis, cols)

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _touch(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def main():
    root = tempfile.mkdtemp(prefix="vault_test_")
    src = os.path.join(root, "src")
    out = os.path.join(root, "vault")
    print(f"workspace: {root}\n")

    # ── disposable source files ─────────────────────────────────────────────
    # Well SMITH 1 — three file types (the multi-type case your real data lacks)
    f_las = _touch(os.path.join(src, "smith_1.las"), b"LASDATA")
    f_pdf = _touch(os.path.join(src, "smith_1_dirsurvey.pdf"), b"%PDF-1.4")
    f_doc = _touch(os.path.join(src, "smith_1_completion.docx"), b"PK\x03\x04docx")
    # Well JONES 2 — single type (control)
    f_las2 = _touch(os.path.join(src, "jones_2.las"), b"LASDATA2")
    # 2D survey GULF SHELF (2011) — volume + nav
    f_sgy = _touch(os.path.join(src, "gulf_shelf.sgy"), b"SEGY2D")
    f_p190 = _touch(os.path.join(src, "gulf_shelf.p190"), b"NAV2D")
    # 3D survey DELTA 3D (no date) — volume + nav
    f_segy = _touch(os.path.join(src, "delta_3d.segy"), b"SEGY3D")
    f_p3 = _touch(os.path.join(src, "delta_3d.p190"), b"NAV3D")
    # nav-only survey ORPHAN — no volume to inherit dim/year
    f_orph = _touch(os.path.join(src, "orphan.p190"), b"NAVORPHAN")

    # ── canned catalog rows (column order matches vault()'s unpack) ──────────
    # wells: (inv, file_path, uwi14, country, state, well_name)
    wells = [
        ("00000000000000000000000000000000000a0001", f_las,  "42317123450000", "US", "TX", "SMITH 1"),
        ("00000000000000000000000000000000000a0002", f_pdf,  "42317123450000", "US", "TX", "SMITH 1"),
        ("00000000000000000000000000000000000a0003", f_doc,  "42317123450000", "US", "TX", "SMITH 1"),
        ("00000000000000000000000000000000000b0001", f_las2, "42317999990000", "US", "TX", "JONES 2"),
    ]
    # seismic: (inv, file_path, survey, country, state, dim, survey_date)
    seis = [
        ("00000000000000000000000000000000000c0001", f_sgy,  "GULF SHELF", "US", "TX", "2D", "2011-06-01"),
        ("00000000000000000000000000000000000c0002", f_p190, "GULF SHELF", "US", "TX", None, None),
        ("00000000000000000000000000000000000d0001", f_segy, "DELTA 3D",   "US", "LA", "3D", None),
        ("00000000000000000000000000000000000d0002", f_p3,   "DELTA 3D",   "US", "LA", None, None),
        ("00000000000000000000000000000000000e0001", f_orph, "ORPHAN NAV", "US", "OK", None, None),
    ]

    cols = {
        "REF": {"UWI14", "PROVINCE_STATE", "COUNTRY", "WELL_NAME", "UWI_SUSPECT"},
        "FILE_WELL_HEADER": {"UWI14", "WELL_NAME", "STATE", "COUNTRY"},
        "FILE_SEIS_HEADER": {"SURVEY_NAME", "SEIS_SET_TYPE", "SURVEY_DATE", "STATE", "COUNTRY"},
    }

    conn = _FakeConn(wells, seis, cols)
    args = SimpleNamespace(
        vault=out,
        default_country="US",
        seis_ext="segy,sgy,seg,p190,p90,p1",
        no_wells=False,
        no_seis=False,
        ref="WELL_REF.well_ref.well_master_gold",
        dry_run=False,
        limit=0,
        report=os.path.join(root, "report.csv"),
        server="(fake)",
        database="(fake)",
        inv_filter=None,
    )

    vault_copy.vault(conn, args, log=print)

    # ── show the tree ───────────────────────────────────────────────────────
    built = []
    for dirpath, _dirs, files in os.walk(out):
        for fn in files:
            rel = os.path.relpath(os.path.join(dirpath, fn), out)
            built.append(rel.replace(os.sep, "\\"))
    print("\n──────── vault tree ────────")
    for p in sorted(built):
        print("  " + p)

    # ── assertions ──────────────────────────────────────────────────────────
    import ntpath
    by_name = {ntpath.basename(b): b for b in built}
    checks = [
        ("smith_1.las",             r"US\TX\42317123450000\SMITH 1\smith_1.las"),
        ("smith_1_dirsurvey.pdf",   r"US\TX\42317123450000\SMITH 1\smith_1_dirsurvey.pdf"),
        ("smith_1_completion.docx", r"US\TX\42317123450000\SMITH 1\smith_1_completion.docx"),
        ("jones_2.las",             r"US\TX\42317999990000\JONES 2\jones_2.las"),
        ("gulf_shelf.sgy",          r"US\TX\2D\2011\GULF SHELF\gulf_shelf.sgy"),
        ("gulf_shelf.p190",         r"US\TX\2D\2011\GULF SHELF\gulf_shelf.p190"),
        ("delta_3d.segy",           r"US\LA\3D\DELTA 3D\delta_3d.segy"),
        ("delta_3d.p190",           r"US\LA\3D\DELTA 3D\delta_3d.p190"),
        ("orphan.p190",             r"US\OK\_UnknownDim\ORPHAN NAV\orphan.p190"),
    ]
    print("\n──────── checks ────────")
    ok = True
    for fname, expect in checks:
        got = by_name.get(fname, "<missing>")
        good = got.endswith(expect)
        ok = ok and good
        print(f"  [{'OK' if good else 'XX'}] {fname:26} -> {got}")

    print()
    print("ALL LAYOUT CHECKS PASSED" if ok else "SOME CHECKS FAILED — see XX above")

    if os.environ.get("KEEP"):
        print(f"\n(KEEP set — tree left at {out})")
    else:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
