r"""copy_n_files.py — copy the first N .las files from a source folder into a test
folder for a trial load. py copy_n_files.py --n 500"""
import os, shutil, argparse
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--dest", default=None)
    ap.add_argument("--move", action="store_true")
    a = ap.parse_args()
    dest = a.dest or (a.src.rstrip("\\/") + f"_{a.n}")
    Path(dest).mkdir(parents=True, exist_ok=True)
    files = sorted(str(p) for p in Path(a.src).glob("*.las"))[:a.n]
    op = shutil.move if a.move else shutil.copyfile
    for fp in files:
        op(fp, os.path.join(dest, os.path.basename(fp)))
    print(f"{'moved' if a.move else 'copied'} {len(files)} .las files -> {dest}")
    print(f"\npoint the pipeline (Run Pipeline / scan folder) at:\n  {dest}")

if __name__ == "__main__":
    main()
