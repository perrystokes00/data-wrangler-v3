"""inspect_h3_bytes.py — the kept result CSV: BCP error shows row 1 space-delimited but
python shows pipes. Look at RAW BYTES of the first row to find the real delimiter/encoding.
py inspect_h3_bytes.py"""
import os, tempfile
p=os.path.join(tempfile.gettempdir(),"h3_result.csv")
print("file:",p,"exists:",os.path.exists(p))
if not os.path.exists(p): raise SystemExit("not found — re-run run_h3 first")
with open(p,"rb") as f: raw=f.read()
print("total size:",len(raw),"bytes")
print("\n=== first 90 bytes as hex ===")
print(raw[:90].hex(" "))
print("\n=== first 90 bytes repr ===")
print(repr(raw[:90]))
print("\n=== what's the byte between fields? (should be 0x7c = '|') ===")
# find first non-alnum byte after position 14 (end of uwi)
first=raw[:80]
for i,b in enumerate(first):
    if i>=14 and b not in range(48,58) and b not in range(97,103):  # not digit/hex
        print(f"  byte at pos {i}: 0x{b:02x} ({chr(b)!r})")
        break
# count delimiters in first line
nl=raw.find(b'\n')
line1=raw[:nl if nl>0 else 80]
print(f"\nfirst line ({len(line1)} bytes): pipes={line1.count(0x7c)}, spaces={line1.count(0x20)}, tabs={line1.count(0x09)}")
print("BOM check: UTF8-BOM",raw[:3]==b'\xef\xbb\xbf'," UTF16LE",raw[:2]==b'\xff\xfe')
