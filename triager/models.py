from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationInfo, field_validator
from sqlalchemy import JSON, Column, Integer, Numeric, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()
SERVICES = ("market-feed", "execution-gateway", "portfolio-ledger")
KINDS = ("tick_gap", "rate_limit", "nav_mismatch", "latency", "ml_degradation")


def now():
    return datetime.now(timezone.utc).isoformat()


class Telemetry(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    service: Literal["market-feed", "execution-gateway", "portfolio-ledger"]
    fill_latency_ms: float = Field(ge=0, le=600000, allow_inf_nan=False)
    slippage_bps: float = Field(ge=-10000, le=10000, allow_inf_nan=False)
    heartbeat_jitter_ms: float = Field(ge=0, le=600000, allow_inf_nan=False)
    tick_age_ms: float = Field(default=0, ge=0, le=3600000, allow_inf_nan=False)
    reject_code: Literal["OK", "429", "REJECT"] = "OK"
    log: str = Field(default="heartbeat healthy", max_length=1000)

    @field_validator("timestamp")
    @classmethod
    def timezone_required(cls, value, info: ValidationInfo):
        if value.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        age = (datetime.now(timezone.utc) - value).total_seconds()
        historical = bool(info.context and info.context.get("allow_historical"))
        if age < -300 or (age > 300 and not historical):
            raise ValueError("timestamp must be within five minutes of receipt")
        return value


class Event(Base):
    __tablename__ = "telemetry"
    id = Column(String(80), primary_key=True)
    received_at = Column(String, nullable=False)
    service = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    score = Column(Numeric(12, 6), nullable=False)


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(String, primary_key=True)
    service = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    opened_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    evidence = Column(JSON, nullable=False)
    diagnosis = Column(Text, nullable=False)
    action = Column(String, nullable=False)
    occurrences = Column(Integer, nullable=False, default=1)
    report = Column(Text, nullable=False, default="")


class Balance(Base):
    __tablename__ = "balances"
    account = Column(String, primary_key=True)
    local_nav = Column(Numeric(20, 2), nullable=False)
    exchange_nav = Column(Numeric(20, 2), nullable=False)


class Audit(Base):
    __tablename__ = "audit"
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(String, nullable=False)
    incident_id = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)
    detail = Column(JSON, nullable=False)


class ServiceWatermark(Base):
    __tablename__ = "service_watermarks"
    service = Column(String, primary_key=True)
    event_timestamp = Column(String, nullable=False)
