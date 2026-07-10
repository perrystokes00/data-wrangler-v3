"""check_fk_deployed.py — is the FK review grid actually wired in? Checks that
promote_fk_review.py exists in modules AND page_workbench.py has the render call.
py check_fk_deployed.py"""
import os
def find(name, dirs):
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.exists(p): return p
    return None

here = os.getcwd()
mods = os.path.join(here, "modules")

fk = find("promote_fk_review.py", [mods, here])
print("promote_fk_review.py in modules:", "YES -> "+fk if fk else "NO  <-- copy it to modules\\")

pw = find("page_workbench.py", [here, os.path.join(here,"pages")])
if pw:
    s = open(pw, encoding="utf-8").read()
    wired = "render_promote_fk" in s or "_render_promote_fk" in s
    print("page_workbench.py has FK render call:", "YES" if wired else "NO  <-- run patch_wire_fk_review.py")
    print("page_workbench.py has scorecard docs fix:", "YES" if "docs_done" in s else "NO  <-- run patch_scorecard_docs.py")
else:
    print("page_workbench.py: NOT FOUND")

print("\nFor the FK grid to appear after a run, BOTH must be YES.")
