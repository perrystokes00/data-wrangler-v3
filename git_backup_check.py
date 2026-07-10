"""git_backup_check.py — check the repo's git state before backing up: is it a repo already,
what's the remote, how big is the working tree, and what SHOULD be gitignored. Read-only.
py git_backup_check.py"""
import os, subprocess, sys
ROOT = os.getcwd()
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
def run(cmd):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, shell=True).stdout.strip()
    except Exception as e:
        return f"ERR {e}"

log("=== is this a git repo? ===")
inside = run("git rev-parse --is-inside-work-tree")
log(f"  inside work tree: {inside or '(no — not a git repo yet)'}")
if inside == "true":
    log(f"  current branch: {run('git branch --show-current')}")
    log(f"  remote(s): {run('git remote -v') or '(none)'}")
    log(f"  last commit: {run('git log -1 --oneline') or '(no commits yet)'}")
    status = run("git status --porcelain")
    log(f"  uncommitted changes: {len(status.splitlines())} file(s)")

log("\n=== working tree size (what a naive commit would include) ===")
total = nfiles = 0
big_dirs = {}
for dp, dns, fns in os.walk(ROOT):
    if ".git" in dp: continue
    for fn in fns:
        try:
            sz = os.path.getsize(os.path.join(dp,fn)); total += sz; nfiles += 1
            top = os.path.relpath(dp, ROOT).split(os.sep)[0] or "."
            big_dirs[top] = big_dirs.get(top,0) + sz
        except Exception: pass
log(f"  total: {nfiles} files, {total//1024//1024} MB")
log("  largest top-level dirs:")
for d,sz in sorted(big_dirs.items(), key=lambda x:-x[1])[:10]:
    log(f"    {sz//1024//1024 or 1:4} MB  {d}")

log("\n=== should be gitignored (don't commit these) ===")
suspects = ["venv",".venv","__pycache__",".vs","download","_trash","node_modules",".idea"]
for s in suspects:
    p = os.path.join(ROOT, s)
    if os.path.exists(p):
        log(f"    EXISTS: {s}\\  <- add to .gitignore")

log("\n=== recommendation ===")
if inside != "true":
    log("  NOT a git repo yet. Plan:")
    log("   1. Write a .gitignore (exclude venv, __pycache__, .vs, download, _trash, *.bak)")
    log("   2. git init")
    log("   3. git add -A ; git commit -m 'snapshot before cleanup'")
    log("   4. (optional) create a private GitHub repo + push")
else:
    log("  Already a repo. Plan:")
    log("   1. Ensure .gitignore covers venv/__pycache__/.vs/download/_trash")
    log("   2. git add -A ; git commit -m 'snapshot before cleanup'")
    log("   3. git push (if a remote exists) or add one")
open(os.path.join(ROOT,"git_backup_check.txt"),"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to git_backup_check.txt")
