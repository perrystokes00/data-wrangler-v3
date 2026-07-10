"""kill_all_py.py — show every python process (so you can see if the app is alive),
then kill pipeline runners + streamlit. py kill_all_py.py         (show)
                                          py kill_all_py.py --kill  (kill)"""
import subprocess, sys

show = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' } | "
        "ForEach-Object { \"{0}  {1}\" -f $_.ProcessId, $_.CommandLine }")
r = subprocess.run(["powershell", "-NoProfile", "-Command", show],
                   capture_output=True, text=True)
print("=== python processes ===")
for ln in (r.stdout or "").splitlines():
    ln = ln.strip()
    if not ln:
        continue
    tag = ""
    if "streamlit" in ln.lower(): tag = "  <-- THE APP"
    elif "pipeline_proc_runner" in ln or "pipeline_run" in ln: tag = "  <-- pipeline runner"
    elif "run_load" in ln: tag = "  <-- run_load (ok, your CLI load)"
    print(" ", ln[:160], tag)

if "--kill" in sys.argv:
    kill = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
            "'streamlit|pipeline_proc_runner|pipeline_run' } | ForEach-Object { "
            "Write-Output $_.ProcessId; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    k = subprocess.run(["powershell", "-NoProfile", "-Command", kill],
                       capture_output=True, text=True)
    print("\nkilled:", [x for x in (k.stdout or "").split() if x.isdigit()] or "none")
    print("app + pipeline runners killed. now run:  py run_load.py")
else:
    print("\n--kill to kill streamlit + pipeline runners (leaves your shell alone)")
