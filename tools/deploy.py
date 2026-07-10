"""
deploy.py — copy the newest matching file from Downloads into this app folder
and print a fingerprint so you KNOW the right build landed (no more "OLD" loops).

Usage:
    py deploy.py vault_organizer
    py deploy.py promote_catalog
    py deploy.py pipeline_run
    py deploy.py vault_organizer pipeline_run      # several at once

For each name it:
  - finds the newest Downloads file matching <name>*.py (handles "(1)", "(2)" dupes)
  - copies it over <name>.py in the current folder
  - prints size, mtime, a short content hash, and any known build markers found

Add markers for a module here so the fingerprint means something:
"""
import glob, os, shutil, sys, time, hashlib

# substrings that identify a given build; edit freely
MARKERS = {
    "vault_organizer":  ["vault-wait", "READ UNCOMMITTED", "OBJECT_ID(:full)"],
    "promote_catalog":  ["cache_hit", "CHECKSUM_AGG", "prime_sub"],
    "pipeline_run":     ["VAULT_COPY_WORKERS", "[vault-phase]", "[vault-fetch]"],
}
DOWNLOADS = os.path.join(os.path.expanduser("~"), "Downloads")


def deploy(name):
    name = name[:-3] if name.endswith(".py") else name
    pat = os.path.join(DOWNLOADS, name + "*.py")
    hits = glob.glob(pat)
    if not hits:
        print(f"[{name}] NO match in Downloads for {name}*.py"); return False
    src = max(hits, key=os.path.getmtime)
    dst = os.path.join(os.getcwd(), name + ".py")
    shutil.copyfile(src, dst)
    body = open(dst, encoding="utf-8", errors="replace").read()
    h = hashlib.md5(body.encode("utf-8", "replace")).hexdigest()[:8]
    mtime = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(src)))
    found = [m for m in MARKERS.get(name, []) if m in body]
    print(f"[{name}] <- {os.path.basename(src)}  ({len(body):,}B · {mtime} · {h})")
    if MARKERS.get(name):
        print(f"          markers: {', '.join(found) if found else 'NONE — stale/wrong file?'}")
    if len(hits) > 1:
        others = sorted((os.path.basename(x) for x in hits if x != src))
        print(f"          note: {len(hits)} Downloads copies exist; used newest. "
              f"others: {', '.join(others)}")
    return True


if __name__ == "__main__":
    names = sys.argv[1:] or list(MARKERS)
    ok = all(deploy(n) for n in names)
    sys.exit(0 if ok else 1)
