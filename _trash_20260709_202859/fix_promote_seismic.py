r"""fix_promote_seismic.py — the resilient survey-blob patch's greedy regex damaged
promote_catalog.py so 'promote_seismic' is no longer defined (NameError at run_promote).
This inspects the current file + .bak, reports the damage, and if the .bak still has a
valid promote_seismic, restores from it. py fix_promote_seismic.py  (report only)
                                          py fix_promote_seismic.py --restore
"""
import os, sys, ast
P = "promote_catalog.py"
if not os.path.exists(P):
    P = os.path.join("modules","promote_catalog.py")
BAK = P + ".bak"

def check(path):
    if not os.path.exists(path):
        return f"{path}: MISSING"
    s = open(path, encoding="utf-8").read()
    has_def = "def promote_seismic" in s
    try:
        ast.parse(s); parses = "parses OK"
    except SyntaxError as e:
        parses = f"SYNTAX ERROR line {e.lineno}: {e.msg}"
    # is promote_seismic referenced but not defined?
    calls = s.count("promote_seismic")
    defs  = s.count("def promote_seismic")
    return (f"{path}:\n   def promote_seismic present: {has_def}\n"
            f"   'promote_seismic' mentions: {calls}, definitions: {defs}\n"
            f"   {parses}\n"
            f"   survey-blob resilient block: {'yes' if 'survey-blob resilient' in s else 'no'}\n"
            f"   survey-blob aggregation block: {'yes' if 'survey-blob aggregation' in s else 'no'}")

print("=== CURRENT ===")
print(check(P))
print("\n=== .bak ===")
print(check(BAK))

if "--restore" in sys.argv:
    if not os.path.exists(BAK):
        sys.exit("no .bak to restore from")
    bs = open(BAK, encoding="utf-8").read()
    if "def promote_seismic" not in bs:
        sys.exit("REFUSING: .bak also lacks promote_seismic — don't restore, we'll rebuild instead")
    try:
        ast.parse(bs)
    except SyntaxError as e:
        sys.exit(f"REFUSING: .bak has syntax error line {e.lineno} — don't restore")
    # save the broken one, restore the bak
    import shutil
    shutil.copy2(P, P + ".broken")
    shutil.copy2(BAK, P)
    print(f"\nRESTORED {P} from {BAK} (broken saved as {P}.broken)")
    print("verify:", check(P).splitlines()[3])
