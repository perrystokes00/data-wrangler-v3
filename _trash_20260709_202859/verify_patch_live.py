"""verify_patch_live.py — is the nested-pool patch actually on disk, and did the last
run use the fast-path (thread mode)? Checks the deployed bcp_capture.py + scans the
newest pipeline log for the BCP fast-path lines. py verify_patch_live.py"""
import os, glob, datetime
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
def find(name):
    for p in (os.path.join(APP, name), os.path.join(APP, "modules", name)):
        if os.path.exists(p): return p
    return None

print("=== 1) is the patch on the DEPLOYED bcp_capture.py? ===")
p = find("bcp_capture.py")
if not p:
    print("   bcp_capture.py NOT FOUND in app dir!");
else:
    s = open(p, encoding="utf-8", errors="replace").read()
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"   {p}")
    print(f"   modified: {mt}  size: {len(s):,}")
    print(f"   has nested-pool patch: {'YES' if 'nested-pool safe' in s else 'NO — OLD FILE, patch not deployed here'}")
    print(f"   has parent_process check: {'YES' if 'parent_process' in s else 'NO'}")
    print(f"   has ThreadPoolExecutor: {'YES' if 'ThreadPoolExecutor' in s else 'NO'}")

print("\n=== 2) newest pipeline log — did the BCP fast-path run, and in which mode? ===")
logs = []
for d in (r"C:\Bulk\reports", os.path.join(APP, "reports")):
    logs += glob.glob(os.path.join(d, "*.log")) + glob.glob(os.path.join(d, "pipeline*.txt")) + glob.glob(os.path.join(d, "run_*.md"))
logs = sorted(set(logs), key=lambda x: os.path.getmtime(x), reverse=True)
if not logs:
    print("   no pipeline logs found in C:\\Bulk\\reports")
else:
    lg = logs[0]
    print(f"   newest log: {os.path.basename(lg)}  ({datetime.datetime.fromtimestamp(os.path.getmtime(lg)):%Y-%m-%d %H:%M:%S})")
    txt = open(lg, encoding="utf-8", errors="replace").read()
    hits = [ln for ln in txt.splitlines() if any(k in ln for k in
            ("bcp-capture", "LAS fast-path", "BCP", "parse pool", "bootstrapping",
             "process pool failed", "nested-process"))]
    if hits:
        print("   BCP-related log lines:")
        for h in hits[-15:]:
            print("     " + h.strip()[:150])
    else:
        print("   NO BCP/fast-path lines in the log — fast-path may not have run,")
        print("   or capture used a different path (thread mode in-app vs process mode).")

print("\n=== 3) which parse_mode does the run use? (fast-path only runs in the parallel capture) ===")
print("   The LAS BCP fast-path is inside the PARALLEL capture branch (parse_mode='process',")
print("   i.e. 'Use all CPU cores' ON, detached run). If you ran in-app THREAD mode, the")
print("   sequential path runs instead — which uses _do_extract/_load_rows_to_catalog, NOT")
print("   the BCP fast-path and NOT worker_core._do_las. Confirm cores were ON.")
