"""Read-only database check; never print credentials or connection URLs."""

import os
import re
import sys

import httpx
from sqlalchemy import text

from triager.config import Settings
from triager.db import Database


def main():
    settings = Settings()
    settings.validate()
    database = Database(settings.database_url)
    try:
        with database.engine.connect() as db:
            db.execute(text("SELECT 1"))
        print(f"Database: OK ({database.engine.dialect.name})")
    except Exception as exc:
        print("Database: FAILED (" + type(exc).__name__ + ")")
        return 1
    finally:
        database.engine.dispose()
    if "--models" in sys.argv:
        try:
            response = httpx.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": os.getenv("GEMINI_API_KEY", "")},
                timeout=20,
            )
            if response.status_code != 200:
                print(f"Gemini model discovery: HTTP {response.status_code}")
                return 1
            models = [
                m["name"]
                for m in response.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
                and re.fullmatch(r"models/gemini-[a-zA-Z0-9._-]+", m.get("name", ""))
            ]
            print("Gemini authentication: OK")
            print(
                "Configured model: "
                + (
                    settings.gemini_model
                    if re.fullmatch(r"gemini-[a-zA-Z0-9._-]+", settings.gemini_model)
                    else "invalid identifier"
                )
            )
            print("Available generation models: " + ", ".join(models[:25]))
        except Exception as exc:
            print(f"Gemini model discovery failed ({type(exc).__name__})")
            return 1
    else:
        print(
            "Gemini: offline"
            if settings.ai_provider == "offline"
            else "Gemini: configured; use incident triage to verify API access"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
