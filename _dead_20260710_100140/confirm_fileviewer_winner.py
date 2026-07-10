"""confirm_fileviewer_winner.py — before shimming modules->root, confirm root has the
fixes and modules has nothing root lacks. Check the _view_text_fallback usage diff and
scan for any modules-only logic. py confirm_fileviewer_winner.py"""
import os, difflib
ROOT=os.getcwd()
rp=os.path.join(ROOT,"file_viewer.py"); mp=os.path.join(ROOT,"modules","file_viewer.py")
a=open(rp,encoding="utf-8",errors="replace").read().splitlines()
b=open(mp,encoding="utf-8",errors="replace").read().splitlines()

print("=== does root have the two fixes? ===")
ra="\n".join(a); rb="\n".join(b)
print(f"  root _vsection (nest-safe):      {'_vsection' in ra}")
print(f"  root PyMuPDF PDF render:         {'fitz' in ra and 'get_pixmap' in ra}")
print(f"  modules base64 iframe (crashy):  {'base64' in rb and 'iframe' in rb}")
print(f"  modules st.expander (nest-crash):{rb.count('st.expander')}")

print("\n=== is there ANY logic in modules NOT in root? (lines only in modules) ===")
sm=difflib.SequenceMatcher(None,a,b)
mod_only=[]
for tag,i1,i2,j1,j2 in sm.get_opcodes():
    if tag in ("insert","replace"):
        for j in range(j1,j2):
            ln=b[j].strip()
            # ignore pure st.expander swaps and blank/comment lines
            if ln and "st.expander" not in ln and not ln.startswith("#") and "base64" not in ln and "iframe" not in ln:
                mod_only.append(b[j])
print(f"  substantive modules-only lines (excluding expander/base64 swaps): {len(mod_only)}")
for ln in mod_only[:20]:
    print(f"    {ln[:88]}")

print("\n=== VERDICT ===")
if not mod_only:
    print("  modules has NOTHING root lacks (only the older expander/base64 approach).")
    print("  -> root is strictly better. Make root canonical, shim modules -> root.")
else:
    print("  modules has some unique lines above — review them before shimming.")
