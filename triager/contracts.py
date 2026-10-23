"""Provider-independent diagnosis contracts and evidence provenance.

Evidence identity proves provenance, not that a hypothesis is true.
"""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal["tick_gap", "rate_limit", "nav_mismatch", "latency", "ml_degradation", "unknown"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(Contract):
    source: str = Field(min_length=1)
    service: str = Field(min_length=1)
    observed_at: datetime
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_timezone(self):
        if self.observed_at.tzinfo is None:
            raise ValueError("Evidence timestamp must include timezone")
        return self

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()

    @property
    def evidence_id(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class IncidentInput(Contract):
    service: str
    evidence: tuple[Evidence, ...]


class Hypothesis(Contract):
    cause: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class Diagnosis(Contract):
    schema_version: Literal["1"] = "1"
    severity: Literal["critical", "high", "medium", "low", "unknown"]
    category: Category
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    hypotheses: tuple[Hypothesis, ...] = ()
    missing_information: tuple[str, ...] = ()
    abstained: bool = False

    @model_validator(mode="after")
    def require_reasoning(self):
        if self.abstained and not self.missing_information:
            raise ValueError("Abstention requires missing information")
        if not self.abstained and not self.hypotheses:
            raise ValueError("Diagnosis requires a cited hypothesis")
        return self


def unsupported_citations(report: Diagnosis, evidence: tuple[Evidence, ...]) -> set[str]:
    """Check reference membership; semantic claim support requires separate verification."""
    available = {item.evidence_id for item in evidence}
    return {ref for hypothesis in report.hypotheses for ref in hypothesis.evidence_ids} - available
