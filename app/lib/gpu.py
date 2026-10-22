"""Optional per-process GPU execution evidence, separate from allocation logs."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def engine_snapshot(pid):
    if os.name == "nt":
        # The ID is an integer obtained from our own child process, not model text.
        command = ("$ErrorActionPreference='Stop'; @(Get-CimInstance "
                   "Win32_PerfRawData_GPUPerformanceCounters_GPUEngine | "
                   f"Where-Object {{$_.Name -like '*pid_{int(pid)}_*'}} | "
                   "Select-Object -Property @('Name','RunningTime')) | ConvertTo-Json -Compress")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                               capture_output=True, text=True, timeout=15)
            if r.returncode or not r.stdout.strip():
                return {}
            rows = json.loads(r.stdout)
            if isinstance(rows, dict):
                rows = [rows]
            return {row["Name"]: int(row["RunningTime"]) * 100 for row in rows if row.get("RunningTime") is not None}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {}
    result = {}
    for info in Path(f"/proc/{int(pid)}/fdinfo").glob("*"):
        try:
            data = info.read_text()
        except OSError:
            continue
        client = re.search(r"^drm-client-id:\s*(\S+)", data, re.M)
        device = re.search(r"^drm-pdev:\s*(\S+)", data, re.M)
        if not client:
            continue
        identity = (device[1] if device else "device") + ":" + client[1]
        for engine, count in re.findall(r"^drm-engine-([^:\s]+):\s*(\d+)\s+ns", data, re.M):
            key = identity + ":" + engine
            result[key] = max(result.get(key, 0), int(count))
    return result


def nvidia_monitor():
    binary = shutil.which("nvidia-smi")
    if not binary:
        return None
    try:
        return subprocess.Popen([binary, "pmon", "-c", "4", "-d", "1", "-s", "u"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError:
        return None


def nvidia_activity(monitor, pid):
    if monitor is None:
        return False
    try:
        output, _ = monitor.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        monitor.kill()
        monitor.communicate()
        return False
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == str(pid) and parts[3].isdigit() and int(parts[3]) > 0:
            return True
    return False
