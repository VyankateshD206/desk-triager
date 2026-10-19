# Publish to GitHub

Suggested repository name: **desk-triager**

Suggested description:

> Python trading-service observability with anomaly detection, SQL reconciliation, AI-assisted triage, and approval-gated simulated recovery.

Suggested topics: `python`, `fastapi`, `observability`, `incident-response`, `trading-systems`, `anomaly-detection`, `isolation-forest`, `postgresql`, `gemini-api`.

## Before the first push

Run from the project root:

```bash
source .venv/bin/activate
pytest -q
ruff check triager tests scripts
ruff format --check triager tests scripts
node --check triager/static/app.js
git status --short
```

The `.gitignore` excludes `.env` variants, credentials, certificates, local database files, virtual environments, and generated caches. `.env.example` contains placeholders and is intended for source control. Local credentials and runtime history do not belong in the repository.

The README screenshot uses simulated data. Replace it after UI changes so the landing page matches the application.

## First push

Create an empty repository in your GitHub account. Then run the following, substituting your actual username and repository URL:

```bash
git add .
git diff --cached --stat
git commit -m "Release Desk Triager portfolio application"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/desk-triager.git
git push -u origin main
```

If a remote is already configured, use its existing URL rather than adding another `origin`. Review the staged file list before committing. Configure your Git name/email locally if Git requests it; use your own identity.

After pushing, verify the **Checks** workflow under Actions, confirm the README image renders, and add the repository description and topics. Only add a passing CI badge after a real run succeeds. Choose the repository's license and visibility before public distribution.

This repository preparation does not itself create a GitHub repository or publish any files.
