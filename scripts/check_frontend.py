"""Optional Node syntax validation for the vanilla JavaScript console; no npm wrapper."""

import shutil
import subprocess

node = shutil.which("node")
if node:
    subprocess.run([node, "--check", "triager/static/app.js"], check=True)
else:
    print("Node unavailable: skipped optional frontend syntax check")
