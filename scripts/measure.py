"""Run a command and report wall time and peak RSS of its process tree (Linux). Used by perf reports."""
import json
import resource
import subprocess
import sys
import time

start = time.perf_counter()
proc = subprocess.run(sys.argv[1:], capture_output=True, text=True, check=False)
wall = time.perf_counter() - start
rss_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
sys.stdout.write(proc.stdout)
sys.stderr.write(json.dumps({"measure": {"wall_s": round(wall, 2), "peak_rss_mb": round(rss_kb / 1024, 1),
                                         "exit": proc.returncode}}) + "\n")
sys.exit(proc.returncode)
