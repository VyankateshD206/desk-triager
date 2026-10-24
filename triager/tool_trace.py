"""Bounded, redacted tool audit records; model-planning usage is recorded separately."""

import json
import time

from .models import now
from .security import sanitize


def event(name, arguments, service, started, status, result, evidence_ids=()):
    safe = sanitize(result)
    preview = json.dumps(safe, sort_keys=True)
    record = {
        "tool": name,
        "arguments": sanitize(arguments),
        "scope": {"service": service},
        "at": now(),
        "status": status,
        "latency_ms": (time.perf_counter() - started) * 1000,
        "result_summary": preview[:600],
        "summary_truncated": len(preview) > 600,
        "evidence_ids": list(evidence_ids),
        "token_usage": "not_applicable_to_read_only_tool",
    }

    if name == "search_runbooks" and status == "ok":
        try:
            documents = json.loads(safe["result"]["content"])
        except (KeyError, TypeError, ValueError):
            documents = []
        record["retrieved_documents"] = (
            [
                {
                    key: doc[key]
                    for key in ("document_id", "version", "chunk_id", "source", "embedding_version")
                    if isinstance(doc.get(key), str)
                }
                for doc in documents
                if isinstance(doc, dict)
            ]
            if isinstance(documents, list)
            else []
        )
    return record
