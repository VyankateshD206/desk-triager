import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Process environment wins; Neon .env.local values take precedence over .env.
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL") or "sqlite:///./desk.db"
    token: str = os.getenv("DESK_TOKEN", "local-access-token")
    simulator: bool = os.getenv("SIMULATOR_ENABLED", "true").lower() == "true"
    ai_provider: str = os.getenv("AI_PROVIDER", "offline")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    tick_gap_seconds: float = float(os.getenv("TICK_GAP_SECONDS", "8"))

    def validate(self):
        if self.ai_provider not in {"offline", "gemini"}:
            raise ValueError("AI_PROVIDER must be offline or gemini")
        if self.tick_gap_seconds < 3:
            raise ValueError("TICK_GAP_SECONDS must be at least 3")
        if not self.token:
            raise ValueError("DESK_TOKEN is required")
