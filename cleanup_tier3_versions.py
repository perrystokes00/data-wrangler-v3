r"""
cleanup_tier3_versions.py — Tier 3: remove confirmed OLD version-duplicate files.
Based on analyze_tier3_versions.py, with two false positives PROTECTED:
  - app_v3.py       = the live entry point (matched '_v3' but is NOT a dupe) — KEEP
  - vault_copy.py   = a live module imported by 2 pages (matched '_copy') — KEEP

PREVIEWS by default; --apply moves to _trash_tier3_<ts> (recoverable); --hard deletes.
py cleanup_tier3_versions.py [--apply] [--hard]
"""
import os, sys, shutil, time
APPLY="--apply" in sys.argv; HARD="--hard" in sys.argv
ROOT=os.getcwd()

# confirmed-old version files safe to remove (relative paths)
DELETE=[
    "backup\\app_v3.py",
    "find_uom_ref (1).py",
    "geojson\\load_kgs_geojson (8).py",
    "load_ks_header_to_gold (5).py",
    "page_file_catalog_v3.py",
    "page_pipeline_old.py",
    "page_pipeline_v3.py",
    "page_pipeline_tools (1).py",
    "page_selected_documents (12).py",
    "page_selected_documents_old.py",
    "page_well_documents - Copy.py",
    "page_well_map - Copy.py",
    "page_wl_map_old.py",
]
# explicitly protected (false positives — never delete)
PROTECT=["app_v3.py", "vault_copy.py"]

print(f"{'APPLY -> ' + ('HARD DELETE' if HARD else '_trash') if APPLY else 'PREVIEW'}\n")
print("PROTECTED (never touched):", PROTECT, "\n")

present=[]; missing=[]
for rel in DELETE:
    p=os.path.join(ROOT,rel)
    (present if os.path.exists(p) else missing).append(rel)

print(f"will remove {len(present)} old-version file(s):")
tot=0
for rel in present:
    sz=os.path.getsize(os.path.join(ROOT,rel)); tot+=sz
    print(f"   {sz//1024:>5}KB  {rel}")
if missing:
    print(f"\n(not present, skipping): {missing}")
print(f"\ntotal: {tot//1024} KB")

if not APPLY:
    print("\n(preview) re-run with --apply to move to _trash_tier3_<ts>, or --apply --hard to delete.")
    sys.exit()

# safety: never touch protected even if somehow listed
present=[r for r in present if os.path.basename(r) not in PROTECT]

if HARD:
    for rel in present:
        try: os.remove(os.path.join(ROOT,rel))
        except Exception as e: print(f"  skip {rel}: {e}")
    print(f"\ndeleted {len(present)} file(s).")
else:
    trash=os.path.join(ROOT,"_trash_tier3_"+time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(trash,exist_ok=True)
    for rel in present:
        try: shutil.move(os.path.join(ROOT,rel), os.path.join(trash, rel.replace("\\","__")))
        except Exception as e: print(f"  skip {rel}: {e}")
    print(f"\nmoved {len(present)} file(s) to {trash}")
    print("Run the app to confirm, then delete that folder.")
