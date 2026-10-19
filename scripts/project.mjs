// npm commands delegate to the Python application; no Node service is introduced.
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const localPython = join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.PYTHON || (existsSync(localPython) ? localPython : "python3");
function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", env: process.env });
  if (result.error) {
    console.error(`Unable to start ${command}. Install the project development dependencies first.`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status || 1);
}
const task = process.argv[2];
if (task === "build") {
  run(python, ["-m", "ruff", "check", "triager", "tests", "scripts"]);
  run(python, ["-m", "ruff", "format", "--check", "triager", "tests", "scripts"]);
  run(process.execPath, ["--check", "triager/static/app.js"]);
  run(python, ["-m", "build", "--wheel", "--no-isolation"]);
  run(python, ["scripts/verify_package.py"]);
  console.log("Build complete: Python wheel and console assets verified.");
} else if (task === "start") {
  run(python, ["-m", "uvicorn", "triager.app:app", "--host", "127.0.0.1", "--port", process.env.PORT || "8000", "--no-access-log", ...process.argv.slice(3)]);
} else if (task === "test") {
  run(python, ["-m", "pytest", "-q"]);
} else if (task === "verify") {
  run(python, ["scripts/verify_services.py", ...process.argv.slice(3)]);
} else {
  console.error("Expected build, start, test, or verify.");
  process.exit(1);
}
