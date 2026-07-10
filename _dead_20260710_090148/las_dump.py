import glob, os
for fp in glob.glob(r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected\*.las")[:3]:
    print("="*60); print(os.path.basename(fp)); print("="*60)
    with open(fp, encoding="utf-8", errors="replace") as f:
        for line in f:
            u = line.upper()
            if line.startswith("~") or "API" in u or "UWI" in u or line.strip().startswith("WELL"):
                print("  ", line.rstrip()[:90])
            if line.startswith("~A") or line.startswith("~ASCII"):
                break
