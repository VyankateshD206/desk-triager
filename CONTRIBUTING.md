# Working on Desk

Use Python 3.11 or later and install the package with development tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp -n .env.example .env
```

Keep credentials in `.env`. Tests use temporary databases and mocked Gemini responses; no cloud account is required.

```bash
ruff format triager tests scripts
ruff check triager tests scripts
node --check triager/static/app.js
pytest -q
```

Validate a relevant failure scenario through detection, review, approval, and verification when changing the incident workflow. Keep synthetic data and simulated recovery clearly identified. Record architectural tradeoffs in `docs/ARCHITECTURE.md` and operational steps in `docs/RUNBOOKS.md`.

Open a pull request describing the problem, changed behavior, and verification results. Use `make build` and `make test`. Schema changes need an Alembic migration and upgrade verification.
