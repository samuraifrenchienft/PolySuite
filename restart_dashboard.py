#!/usr/bin/env python3
"""
Force restart dashboard - kills PolySuite Python processes and starts fresh.
Run this when template/UI changes don't show (old instances still running).
"""

import subprocess
import os
import sys
import time

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

# Use stop script if available, else taskkill python
print("Stopping PolySuite processes...")
stop_ps1 = os.path.join(PROJECT_DIR, "scripts", "stop_polysuite.ps1")
if os.path.exists(stop_ps1):
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", stop_ps1], capture_output=True)
else:
    subprocess.run("taskkill /F /IM python.exe 2>nul", shell=True, capture_output=True)
time.sleep(2)

print("Starting fresh dashboard...")
cmd = [sys.executable, "main.py", "dashboard"]
proc = subprocess.Popen(cmd, cwd=PROJECT_DIR, creationflags=subprocess.CREATE_NEW_CONSOLE)
print(f"Dashboard started with PID: {proc.pid}")
print("(If this fails, check the NEW console window for Python errors — startup can take 5–15s.)\n")

try:
    import requests
except ImportError:
    print("Install requests for post-start check: pip install requests")
    sys.exit(0)

port = os.environ.get("DASHBOARD_PORT", "5000")
base = f"http://127.0.0.1:{port}/"
last_err = None
for attempt in range(1, 21):
    time.sleep(1)
    try:
        r = requests.get(base, timeout=5)
        print(f"Dashboard OK after ~{attempt}s: {r.status_code}")
        break
    except Exception as e:
        last_err = e
        if attempt in (5, 10, 15):
            print(f"  Still waiting ({attempt}s)... {str(e)[:80]}")
else:
    print(
        f"Check dashboard failed after 20s: {last_err}\n"
        f"  Open {base} in a browser manually.\n"
        "  If it never loads: read the dashboard console window (traceback) or run:\n"
        f"    {sys.executable} main.py dashboard"
    )
