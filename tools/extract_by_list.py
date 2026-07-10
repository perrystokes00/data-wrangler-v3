r"""
extract_by_list.py — pull specific LAS files (named in a list) out of the LAS_Files
tree into one folder for loading. Matches by file name (recursive search).

  py extract_by_list.py --list "C:\...\to_load.txt"
  py extract_by_list.py --list "C:\...\wells.csv" --col file_name
  py extract_by_list.py --list names.txt --dest "C:\...\to_load" --move

--list may be a plain text file (one name per line) or a .csv (--col names the
column; auto-detected if omitted). Names may include or omit the .las extension
and any path — only the file name is used.
"""
import sys, os, shutil, argparse
from pathlib import Path

def read_names(path, col=None):
    if path.lower().endswith(".csv"):
        import pandas as pd
        df = pd.read_csv(path, dtype=str)
        if col is None:
            col = next((c for c in df.columns
                        if any(k in c.lower() for k in ("file", "name", "las"))),
                       df.columns[0])
        print(f"  reading column '{col}' from {os.path.basename(path)}")
        return [str(x) for x in df[col].dropna()]
    with open(path, encoding="utf-8", errors="replace") as f:
        return [ln.strip() for ln in f if ln.strip()]

def norm(nm):
    nm = os.path.basename(str(nm).strip().strip('"').strip("'"))
    if nm and not nm.lower().endswith(".las"):
        nm += ".las"
    return nm.lower()

def uniq(dest, name):
    p = os.path.join(dest, name)
    if not os.path.exists(p):
        return p
    stem, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(os.path.join(dest, f"{stem}_{i}{ext}")):
        i += 1
    return os.path.join(dest, f"{stem}_{i}{ext}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files")
    ap.add_argument("--list", required=True)
    ap.add_argument("--col", default=None)
    ap.add_argument("--dest", default=None)
    ap.add_argument("--move", action="store_true")
    a = ap.parse_args()

    dest = a.dest or os.path.join(a.src, "_selected")
    Path(dest).mkdir(parents=True, exist_ok=True)

    wanted = {norm(n) for n in read_names(a.list, a.col)}
    wanted.discard(".las"); wanted.discard("")
    print(f"{len(wanted):,} wanted file name(s)")

    # index the tree once: name(lower) -> full path
    index = {}
    for p in Path(a.src).rglob("*.las"):
        index.setdefault(p.name.lower(), str(p))
    print(f"{len(index):,} .las files under {a.src}")

    op = shutil.move if a.move else shutil.copyfile
    found, missing = 0, []
    for nm in sorted(wanted):
        src = index.get(nm)
        if src:
            op(src, uniq(dest, os.path.basename(src)))
            found += 1
        else:
            missing.append(nm)

    print(f"\n{'moved' if a.move else 'copied'} {found:,} file(s) -> {dest}")
    print(f"missing (not found in tree): {len(missing):,}")
    if missing:
        mf = os.path.join(dest, "_missing.txt")
        with open(mf, "w", encoding="utf-8") as f:
            f.write("\n".join(missing))
        print(f"  missing names -> {mf}")

if __name__ == "__main__":
    main()
