r"""patch_worker_csv.py — route .csv to the office/deep loader in worker_core.
process_file currently has no .csv branch (-> 'no handler for .csv'). Add .csv to
the office route so production CSVs reach _do_office -> dv_office_loader. .bak,
idempotent. py patch_worker_csv.py"""
import os, ast, sys
P = "worker_core.py"
if not os.path.exists(P):
    P = os.path.join("modules", "worker_core.py")
if not os.path.exists(P):
    sys.exit("worker_core.py not found (copy it here)")
s = open(P, encoding="utf-8").read()
if '".ods", ".csv"' in s:
    print("already patched"); sys.exit(0)
old = '''        elif fext in (".xlsx", ".xls", ".docx", ".doc", ".odt", ".ods"):
            res = _do_office(engine, fpath, uwi, inv, say)'''
new = '''        elif fext in (".xlsx", ".xls", ".docx", ".doc", ".odt", ".ods", ".csv"):
            res = _do_office(engine, fpath, uwi, inv, say)'''
if old not in s:
    sys.exit("FAILED: office route anchor not found")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak","w",encoding="utf-8").write(open(P,encoding="utf-8").read())
open(P,"w",encoding="utf-8").write(s)
print(f"patched {P}: .csv now routes to _do_office")
