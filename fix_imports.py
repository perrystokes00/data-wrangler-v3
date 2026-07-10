r"""
fix_imports.py — finish the dataview refactor: relocate 6 shared libraries that were
mis-sorted into tools/ (or stranded in modules/), then rewrite every surviving
`modules.X` reference in the app to its real package path.

Run from the repo root, AFTER committing the v4 refactor.
  py fix_imports.py            # DRY RUN — shows git mv plan + every rewrite
  py fix_imports.py --apply

Only touches real import statements (anchored `from modules.X import` / `import modules.X`)
and the dynamic string "dataview.core.fk_catalog" / 'dataview.core.fk_catalog'. Comments, docstrings,
and print()-strings that merely mention `modules.` are left alone. Every rewritten file is
ast-validated; if a rewrite would break syntax it's skipped with a warning.
"""
import os, re, sys, ast, subprocess

APPLY = "--apply" in sys.argv
ROOT  = os.getcwd()

def git(*a): return subprocess.run(["git", *a], capture_output=True, text=True)

# shared libraries that must move OUT of tools/ (or modules/) INTO the package.
# src (current location, post-refactor)          -> dst (correct package home)
MOVES = {
    "tools/audit_log.py":      "dataview/file_catalog/audit_log.py",
    "tools/las_catalog.py":    "dataview/file_catalog/las_catalog.py",
    "tools/las_loader.py":     "dataview/file_catalog/las_loader.py",
    "tools/extract_petro.py":  "dataview/file_catalog/extract_petro.py",
    "tools/setup_database.py": "dataview/core/setup_database.py",
    "modules/fk_catalog.py":   "dataview/core/fk_catalog.py",
}

# module short-name  ->  new dotted package path (used to rewrite `modules.X`)
REMAP = {
    "db":              "dataview.core.db",
    "schema":          "dataview.core.schema",
    "fk":              "dataview.core.fk",
    "validate":        "dataview.core.validate",
    "ppdm_agent":      "dataview.core.ppdm_agent",
    "fk_catalog":      "dataview.core.fk_catalog",
    "setup_database":  "dataview.core.setup_database",
    "staging":         "dataview.import_data.staging",
    "mapping":         "dataview.import_data.mapping",
    "promote":         "dataview.import_data.promote",
    "survey_loader":   "dataview.file_catalog.survey_loader",
    "audit_log":       "dataview.file_catalog.audit_log",
    "las_catalog":     "dataview.file_catalog.las_catalog",
    "las_loader":      "dataview.file_catalog.las_loader",
    "extract_petro":   "dataview.file_catalog.extract_petro",
}
# names that are still imported but we couldn't place from the dry-run — locate + report
UNKNOWN = ["promote_report_ui", "shapefile_mapping_cache"]

SKIP_DIRS = {"venv",".venv",".git","__pycache__","_refactor_quarantine",
             "_dead","_trash","_archive","schema_registry"}
def skip(dp):
    p = os.path.relpath(dp, ROOT).split(os.sep)
    return bool(p) and (p[0] in SKIP_DIRS or p[0].startswith(("_dead","_trash","_archive")))

def rewrite(src):
    out, hits = src, []
    for name, tgt in REMAP.items():
        # from modules.NAME import ...   (also matches multi-line: only the head line changes)
        pat1 = rf"(?m)^(\s*)from\s+modules\.{re.escape(name)}(\s+import\b)"
        out2 = re.sub(pat1, rf"\1from {tgt}\2", out)
        if out2 != out: hits.append(f"from modules.{name} -> from {tgt}"); out = out2
        # import modules.NAME  (bare)
        pat2 = rf"(?m)^(\s*)import\s+modules\.{re.escape(name)}\b"
        out2 = re.sub(pat2, rf"\1import {tgt}", out)
        if out2 != out: hits.append(f"import modules.{name} -> import {tgt}"); out = out2
    # dynamic string import (only fk_catalog uses this pattern in the app)
    for q in ('"', "'"):
        s, t = f'{q}modules.fk_catalog{q}', f'{q}dataview.core.fk_catalog{q}'
        if s in out: out = out.replace(s, t); hits.append("import_module modules.fk_catalog -> dataview.core.fk_catalog")
    # worker_core fallback tuple: "dataview.file_catalog.survey_loader"
    for q in ('"', "'"):
        s, t = f'{q}modules.survey_loader{q}', f'{q}dataview.file_catalog.survey_loader{q}'
        if s in out: out = out.replace(s, t); hits.append("fallback modules.survey_loader -> dataview.file_catalog.survey_loader")
    return out, hits

# ---- locate the unknowns ----
def find(basename):
    out = []
    for dp,dns,fns in os.walk(ROOT):
        if skip(dp): dns[:]=[]; continue
        dns[:]=[d for d in dns if not skip(os.path.join(dp,d))]
        if basename in fns: out.append(os.path.relpath(os.path.join(dp,basename), ROOT))
    return out

print(f"{'APPLY' if APPLY else 'DRY RUN'} — finish refactor: relocate libs + rewrite modules.* imports\n")

print("STEP 1 — relocate shared libraries (git mv):")
moves_ok = {}
for src, dst in MOVES.items():
    if os.path.exists(os.path.join(ROOT, src)):
        print(f"   git mv {src}  ->  {dst}")
        moves_ok[src] = dst
    else:
        print(f"   SKIP  {src}  (not found — already moved or never here)")
print()

# ---- scan for rewrites (preview) ----
print("STEP 2 — rewrite `modules.X` imports in the app:")
targets = []
for dp,dns,fns in os.walk(ROOT):
    if skip(dp): dns[:]=[]; continue
    dns[:]=[d for d in dns if not skip(os.path.join(dp,d))]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p = os.path.join(dp, fn)
        try: src = open(p, encoding="utf-8", errors="replace").read()
        except OSError: continue
        _, hits = rewrite(src)
        if hits: targets.append((os.path.relpath(p, ROOT), hits))
for rel, hits in sorted(targets):
    print(f"   {rel}")
    for h in sorted(set(hits)): print(f"        {h}")
print(f"\n   {len(targets)} files to rewrite.")

print("\nSTEP 3 — unresolved names (locate for manual decision):")
for n in UNKNOWN:
    locs = find(n + ".py")
    print(f"   {n}: " + (", ".join(locs) if locs else "NOT FOUND anywhere — likely a dead/optional import"))

if not APPLY:
    print("\n(DRY RUN) nothing changed. Review, then --apply.")
    sys.exit()

print("\n--- APPLYING ---")
# 1) git mv
for src, dst in moves_ok.items():
    os.makedirs(os.path.join(ROOT, os.path.dirname(dst)), exist_ok=True)
    r = git("mv", src, dst)
    print(("  moved  " if r.returncode==0 else "  MV FAIL ")+f"{src} -> {dst}"+("" if r.returncode==0 else "  "+r.stderr.strip()))
# 2) rewrites
changed = 0
for dp,dns,fns in os.walk(ROOT):
    if skip(dp): dns[:]=[]; continue
    dns[:]=[d for d in dns if not skip(os.path.join(dp,d))]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p = os.path.join(dp, fn)
        src = open(p, encoding="utf-8", errors="replace").read()
        new, hits = rewrite(src)
        if new != src:
            try: ast.parse(new)
            except SyntaxError as e:
                print(f"  WARN skipped {os.path.relpath(p,ROOT)}: {e}"); continue
            open(p, "w", encoding="utf-8").write(new); changed += 1
print(f"\nrewrote {changed} files. Now: restart Streamlit, run the pipeline, then commit.")
