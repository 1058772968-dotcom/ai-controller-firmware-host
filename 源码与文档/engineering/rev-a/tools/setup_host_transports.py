#!/usr/bin/env python3
"""Install companion transport bindings into a task-owned virtual environment."""
from pathlib import Path
import subprocess,sys,ssl
r=Path(__file__).resolve().parents[1]
folder=Path.home()/('.cache/ai-key-rev-a/host-python314' if getattr(ssl,'HAS_PSK',False) else '.cache/ai-key-rev-a/host-python')
if sys.version_info<(3,10):raise SystemExit('Use Python 3.10 or newer to install BLE bindings.')
if not (folder/'bin/python').exists():subprocess.run([sys.executable,'-m','venv',str(folder)],check=True)
subprocess.run([str(folder/'bin/python'),'-m','pip','install','-r',str(r/'host/requirements-transports.txt')],check=True)
print(folder/'bin/python')
