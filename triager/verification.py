"""Deterministic extract checks. These do not establish semantic or causal support."""

import json
import math
import re
from decimal import Decimal

from .contracts import Diagnosis, Evidence, unsupported_citations

MONETARY_SOURCES = frozenset({"ledger:snapshot", "tool:reconcile_balances"})
MONETARY_FIELDS = frozenset({"local_nav", "exchange_nav", "difference"})
DECIMAL_STRING = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def numeric_value(content, pointer, source=None):
    """Resolve an exact pointer; only known ledger monetary fields permit decimal strings."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("Invalid JSON pointer")
    value = json.loads(content)
    for raw in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", raw):
            raise ValueError("Invalid JSON pointer escape")
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list) and not re.fullmatch(r"0|[1-9][0-9]*", token):
            raise ValueError("Invalid JSON pointer array index")
        value = value[int(token)] if isinstance(value, list) else value[token]
    if isinstance(value, bool):
        raise ValueError("Reference is not a finite number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float) and math.isfinite(value):
        return Decimal(str(value))
    if (
        source in MONETARY_SOURCES
        and token in MONETARY_FIELDS
        and isinstance(value, str)
        and DECIMAL_STRING.fullmatch(value)
    ):
        return Decimal(value)
    raise ValueError("Reference is not a finite number or an allowed ledger decimal")


def verify_support(report: Diagnosis, evidence: tuple[Evidence, ...]) -> tuple[str, ...]:
    issues = []
    if unsupported_citations(report, evidence):
        return ("UnsupportedCitation",)
    available = {item.evidence_id: item for item in evidence}
    for hypothesis in report.hypotheses:
        covered = set()
        for support in hypothesis.supporting_quotes:
            item = available.get(support.evidence_id)
            if not item or support.evidence_id not in hypothesis.evidence_ids:
                issues.append("UncitedSupport")
            elif support.quote not in item.content:
                issues.append("UnsupportedQuote")
            else:
                covered.add(support.evidence_id)
        for claim in hypothesis.numeric_claims:
            item = available.get(claim.evidence_id)
            if not item or claim.evidence_id not in hypothesis.evidence_ids:
                issues.append("UncitedSupport")
                continue
            try:
                if numeric_value(item.content, claim.pointer, source=item.source) != Decimal(
                    str(claim.value)
                ):
                    issues.append("NumericMismatch")
                else:
                    covered.add(claim.evidence_id)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError):
                issues.append("InvalidNumericReference")
        if set(hypothesis.evidence_ids) - covered:
            issues.append("MissingSupport")
    return tuple(sorted(set(issues)))
