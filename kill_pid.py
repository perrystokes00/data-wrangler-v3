"""kill_pid.py — kill a specific pid and confirm. py kill_pid.py 1948"""
import sys, subprocess
if len(sys.argv) < 2:
    sys.exit("usage: py kill_pid.py <pid> [pid2 ...]")
for pid in sys.argv[1:]:
    r = subprocess.run(["powershell","-NoProfile","-Command",
        f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue; "
        f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
        f"{{'still alive'}} else {{'killed'}}"],
        capture_output=True, text=True)
    print(f"  pid {pid}: {(r.stdout or '').strip() or r.stderr.strip()[:60]}")

# what IS 1948? show its command line if still around
r = subprocess.run(["powershell","-NoProfile","-Command",
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
    "'pipeline_proc_runner|pipeline_run|streamlit' } | ForEach-Object { "
    "\"{0}  {1}\" -f $_.ProcessId, $_.CommandLine }"],
    capture_output=True, text=True)
print("\nremaining pipeline/streamlit procs:")
print(" ", (r.stdout or "none").strip()[:300] or "none")
