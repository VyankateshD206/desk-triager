import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Process environment wins; Neon .env.local values take precedence over .env.
load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL") or "sqlite:///./desk.db"
    token: str | None = field(default_factory=lambda: os.getenv("DESK_TOKEN") or None)
    token_file: str = field(
        default_factory=lambda: os.getenv("DESK_TOKEN_FILE") or str(Path.cwd() / ".desk-token")
    )
    simulator: bool = os.getenv("SIMULATOR_ENABLED", "true").lower() == "true"
    ai_provider: str = os.getenv("AI_PROVIDER", "offline")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    tick_gap_seconds: float = float(os.getenv("TICK_GAP_SECONDS", "8"))
    graph_checkpoint_path: str = os.getenv("GRAPH_CHECKPOINT_PATH", "")
    loki_url: str = os.getenv("LOKI_URL", "")
    prometheus_url: str = os.getenv("PROMETHEUS_URL", "")
    demo_service_url: str = os.getenv("DEMO_SERVICE_URL", "")
    agent_max_rounds: int = 4
    agent_max_tools: int = 8
    agent_timeout_seconds: float = 60
    verification_timeout_seconds: float = 30
    verification_samples: int = 2
    retrieval_enabled: bool = os.getenv("RETRIEVAL_ENABLED", "true").lower() == "true"
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "hash")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    fallback_provider: str = os.getenv("FALLBACK_PROVIDER", "offline")
    critic_enabled: bool = os.getenv("CRITIC_ENABLED", "false").lower() == "true"
    critic_provider: str = os.getenv("CRITIC_PROVIDER", "")

    def validate(self):
        if self.critic_provider not in {"", "gemini", "openai"}:
            raise ValueError("Critic provider must be gemini or openai")
        if self.embedding_provider not in {"hash", "gemini"}:
            raise ValueError("Embedding provider must be hash or gemini")
        if self.ai_provider not in {
            "offline",
            "gemini",
            "openai",
        } or self.fallback_provider not in {"offline", "gemini", "openai"}:
            raise ValueError("Providers must be offline, gemini, or openai")
        if self.tick_gap_seconds < 3:
            raise ValueError("TICK_GAP_SECONDS must be at least 3")
        if self.token is not None and (not self.token.strip() or not self.token.isascii()):
            raise ValueError("DESK_TOKEN must be nonempty ASCII")
        if not 1 <= self.agent_max_rounds <= 12 or not 2 <= self.agent_max_tools <= 32:
            raise ValueError("Agent budgets must be rounds 1..12 and tools 2..32")
        if not 1 <= self.agent_timeout_seconds <= 300:
            raise ValueError("Agent timeout must be 1..300 seconds")
        if (
            not 1 <= self.verification_samples <= 10
            or not 3 <= self.verification_timeout_seconds <= 300
        ):
            raise ValueError("Invalid recovery verification limits")
