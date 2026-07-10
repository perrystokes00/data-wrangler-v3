"""
check_fixes.py — verify EVERY fix from this session is present in the file Python
would actually import. Uses find_spec (no execution, no side effects) so it
reports the real on-disk path per module and can't be fooled by a second copy.

Run:  py check_fixes.py
"""
import importlib.util
import os

# module -> [(fix name, marker substring that proves it's present), ...]
CHECKS = {
    "promote_catalog": [
        ("metadata disk cache",        "CHECKSUM_AGG"),
        ("cache-hit fast path",        "cache_hit"),
        ("promote phase timing",       "[promote-phase]"),
    ],
    "vault_organizer": [
        ("_existing_cols sys.columns", "OBJECT_ID(:full)"),
        ("fetch READ UNCOMMITTED",     "READ UNCOMMITTED"),
        ("fetch NVARCHAR bind cast",   "CAST(g.FILE_PATH AS NVARCHAR"),
        ("session-wait diagnostic",    "vault-wait"),
    ],
    "enrich_file_headers": [
        ("pass-1 blank-UWI gate",      "_need1"),
        ("LOOP-join hint",             "INNER LOOP JOIN"),
        ("VARCHAR name key",           "AS VARCHAR(510)"),
        ("NAME_NORM index hint",       "WITH (INDEX(IX_WM_NAME_NORM))"),
    ],
    "worker_core": [
        ("LAS headers-only read",      "ignore_data=True"),
    ],
    "pipeline_run": [
        ("vault parallel copies",      "VAULT_COPY_WORKERS"),
        ("vault phase timing",         "[vault-phase]"),
        ("capture engine reuse",       "_CAP_ENG"),
        ("capture phase timing",       "capture-phase"),
        ("capture LPT + slow-files",   "capture-slow"),
    ],
}


def _path(mod):
    try:
        spec = importlib.util.find_spec(mod)
        if spec and spec.origin and os.path.exists(spec.origin):
            return spec.origin
    except Exception:
        pass
    local = os.path.join(os.getcwd(), mod + ".py")   # fallback: cwd
    return local if os.path.exists(local) else None


def main():
    total = passed = 0
    missing_any = False
    for mod, checks in CHECKS.items():
        path = _path(mod)
        print(f"\n{mod}")
        if not path:
            print("  !! FILE NOT FOUND on the import path")
            missing_any = True
            continue
        src = open(path, encoding="utf-8", errors="replace").read()
        print(f"  {path}")
        for name, marker in checks:
            total += 1
            ok = marker in src
            passed += ok
            missing_any = missing_any or (not ok)
            print(f"    [{'X' if ok else ' '}] {name:26} {'' if ok else 'MISSING'}")

    print("\n" + "=" * 48)
    print(f"{passed}/{total} fixes present on disk.")
    if not missing_any:
        print("ALL FIXES ARE ON DISK. If a full pipeline run still shows old")
        print("timings, the running app is holding old modules in memory —")
        print("that's the only thing left: taskkill /F /IM python.exe, relaunch.")
    else:
        print("Deploy the files with MISSING markers (or run their patch_*.py),")
        print("then re-run this script until it's all X.")


if __name__ == "__main__":
    main()
