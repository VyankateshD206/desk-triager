"""Verify the wheel contains the app and console without local secrets or state."""

from pathlib import Path
from zipfile import ZipFile

wheels = list(Path("dist").glob("desk_triager-*.whl"))
if not wheels:
    raise SystemExit("No application wheel found")
wheel = max(wheels, key=lambda path: path.stat().st_mtime)
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
    required = {
        "triager/app.py",
        "triager/runtime.py",
        "triager/static/index.html",
        "triager/static/app.js",
        "triager/static/style.css",
        "triager/migrations/env.py",
        "triager/migrations/versions/0001_schema.py",
        "triager/knowledge/runbooks.json",
    }
    if not required.issubset(names):
        raise SystemExit("Application or console assets missing from wheel")
    if any(
        Path(name).name.startswith(".env") or name.endswith((".db", ".key", ".pem"))
        for name in names
    ):
        raise SystemExit("Unexpected secret or state file in wheel")
print(
    f"Package verified: {wheel.name}; application + console assets present; no local configuration/state"
)
