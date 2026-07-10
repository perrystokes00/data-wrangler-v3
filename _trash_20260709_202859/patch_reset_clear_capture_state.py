r"""
patch_reset_clear_capture_state.py — demo_reset preserves GLOBAL_FILE_CATALOG
(inventory) but wipes cat_*/dv_*, leaving CAPTURED_HASH / HEADER_EXTRACTED /
CATALOG_READINESS stamped 'already captured' with no cat_* rows behind them. That
contradiction makes the capture stage skip every already-stamped file forever.

Fix: after the clear, reset the capture-progress columns on any preserved
GLOBAL_FILE_CATALOG rows, so a reset yields a consistent 'inventory kept, nothing
captured yet' state. Runs in both full and partial paths. In place, .bak.
py patch_reset_clear_capture_state.py
"""
import sys, os, ast
P = "demo_reset.py"
if not os.path.exists(P):
    P = os.path.join("modules", "demo_reset.py")
if not os.path.exists(P):
    sys.exit("demo_reset.py not found")
s = open(P, encoding="utf-8").read()
if "reset capture-progress columns" in s:
    print("already patched"); sys.exit(0)

# inject right before the final result assembly (after all clears, inside the
# engine.begin() block that ends the function).
anchor = '''    if not result:
        result["(already empty)"] = 0
    result["_reset_version"] = RESET_VERSION'''
inject = '''    # reset capture-progress columns on any PRESERVED inventory rows, so a reset
    # that keeps GLOBAL_FILE_CATALOG doesn't leave files stamped 'captured' with no
    # cat_* rows (which makes the capture stage skip them forever).
    try:
        with engine.begin() as _cc:
            if _cc.execute(text(
                    "SELECT OBJECT_ID('file_catalog.GLOBAL_FILE_CATALOG')")).scalar():
                _sets = []
                for _col in ("CAPTURED_HASH", "HEADER_EXTRACTED", "CATALOG_READINESS",
                             "VAULTED_AT", "PROMOTED_AT"):
                    if _cc.execute(text(
                            f"SELECT COL_LENGTH('file_catalog.GLOBAL_FILE_CATALOG','{_col}')")).scalar():
                        _sets.append(f"{_col} = NULL")
                if _sets:
                    _nrc = _cc.execute(text(
                        "UPDATE file_catalog.GLOBAL_FILE_CATALOG SET "
                        + ", ".join(_sets))).rowcount
                    if _nrc:
                        result["(reset capture-progress columns)"] = int(_nrc)
    except Exception as _e:
        result["(capture-state reset skipped)"] = str(_e)[:80]

    if not result:
        result["(already empty)"] = 0
    result["_reset_version"] = RESET_VERSION'''

if anchor not in s:
    sys.exit("FAILED: result-assembly anchor not found")
s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: reset now clears CAPTURED_HASH/HEADER_EXTRACTED/etc on kept inventory")
