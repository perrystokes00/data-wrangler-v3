"""file_viewer_ground_truth.py — full diff + feature check of the two file_viewer.py copies
so we merge from facts. App imports modules\ (7) more than root (5). py file_viewer_ground_truth.py"""
import os, difflib
ROOT = os.getcwd()
OUT = r"C:\Bulk\reports\fileviewer_diff.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
rp = os.path.join(ROOT,"file_viewer.py")
mp = os.path.join(ROOT,"modules","file_viewer.py")
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
if not (os.path.exists(rp) and os.path.exists(mp)):
    log(f"missing: root={os.path.exists(rp)} modules={os.path.exists(mp)}")
    open(OUT,"w").write("\n".join(L)); raise SystemExit
a = open(rp,encoding="utf-8",errors="replace").read().splitlines()
b = open(mp,encoding="utf-8",errors="replace").read().splitlines()
log(f"root: {len(a)} lines   modules: {len(b)} lines\n")

# feature markers to see what each copy uniquely has
markers = ["_vsection","st.expander","_view_text_fallback","import base64",
           "def view_file","def render","PyMuPDF","fitz","pdfplumber","st.image",
           "Well header","def _","LAS","las","survey","def show"]
log("=== feature markers (root vs modules) ===")
for mk in markers:
    ra = sum(1 for ln in a if mk in ln); rb = sum(1 for ln in b if mk in ln)
    if ra or rb:
        flag = "  <-- DIFFERS" if ra != rb else ""
        log(f"  '{mk}': root={ra} modules={rb}{flag}")

# top-level functions in each (are they the same set?)
import ast
def funcs(src):
    try: return sorted(n.name for n in ast.parse("\n".join(src)).body
                       if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)))
    except Exception as e: return [f"PARSE_ERR {e}"]
fa, fb = funcs(a), funcs(b)
log("\n=== top-level functions ===")
log(f"  root only:    {sorted(set(fa)-set(fb))}")
log(f"  modules only: {sorted(set(fb)-set(fa))}")
log(f"  both:         {sorted(set(fa)&set(fb))}")

log("\n=== full unified diff ===")
diff = list(difflib.unified_diff(a,b,"ROOT","MODULES",lineterm="",n=3))
for line in diff: log(line)

log("\n=== NOTE ===")
log("  Unlike bcp_capture (2 clean separable features), file_viewer diffs are RENDERING")
log("  choices (_vsection vs st.expander). Decide which UI is the one you want to keep,")
log("  then that copy is canonical + shim the other. Likely just pick the newer UI wholesale")
log("  rather than cherry-pick hunks.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)[:2500]); print("\n... full diff in",OUT)
