"""Optional Node syntax and renderer checks for the vanilla JavaScript console."""

import shutil
import subprocess

node = shutil.which("node")
if node:
    subprocess.run([node, "--check", "triager/static/app.js"], check=True)
    subprocess.run([node, "scripts/test_dashboard.cjs"], check=True)
    subprocess.run([node, "scripts/test_incidents.cjs"], check=True)
    subprocess.run([node, "scripts/test_review.cjs"], check=True)
else:
    print("Node unavailable: skipped optional frontend syntax check")
