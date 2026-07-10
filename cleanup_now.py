"""cleanup_now.py — remove this session's throwaway scripts, patchers, and .bak
backups. DRY RUN by default; add --delete to actually remove.
  py cleanup_now.py            # preview
  py cleanup_now.py --delete   # remove
Leaves your real code untouched: worker_core.py, pipeline_run.py, promote_catalog.py,
enrich_file_headers.py, vault_organizer.py, page_*.py, app_v3.py, modules/*.py,
run.py, and the keeper tools (deploy.py, check_fixes.py, run_stage.py, run_vault.py).
"""
import glob, os, sys

PROBES = [
    "spatial_index_probe.py", "log_commit_probe.py", "prime_probe.py",
    "vault_fetch_probe.py", "vault_fetch_probe3.py", "gold_index_probe.py",
    "coll_check.py", "enrich_diag.py", "las_time.py", "las_steps.py",
    "las_incatalog.py", "recovery_check.py", "cc_check.py", "find_ui.py",
    "show_phase.py", "idx_check.py", "wc_state.py", "las_profile.py",
    "map_app.py",
]
junk = [f for f in (PROBES
        + glob.glob("patch_*.py")
        + glob.glob("*.bak") + glob.glob("*.bak2")
        + glob.glob("modules/*.bak") + glob.glob("modules/*.bak2"))
        if os.path.isfile(f)]

if not junk:
    print("nothing to remove — already clean"); sys.exit(0)

print(f"{len(junk)} temp file(s):")
for f in sorted(junk):
    print("  ", f)

if "--delete" not in sys.argv:
    print("\n[dry run] add --delete to remove them.")
else:
    for f in junk:
        try:
            os.remove(f); print("removed", f)
        except Exception as e:
            print("skip", f, e)
    print(f"\ndeleted {len(junk)} file(s).")
