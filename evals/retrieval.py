"""Compare keyword and vector retrieval on independently authored runbook queries."""

import json
import tempfile

from triager.db import Database
from triager.retrieval import Knowledge

QUERIES = [
    ("market-feed", "websocket stale tick transport disconnected", "runbook:feed"),
    ("execution-gateway", "HTTP 429 retry after backoff", "runbook:throttle"),
    ("execution-gateway", "SQL duration high order backlog", "runbook:slow-sql"),
    ("execution-gateway", "retained buffer bytes growing normal SQL", "runbook:memory"),
    ("execution-gateway", "routing retry delay changed after deployment", "runbook:deploy"),
    ("portfolio-ledger", "local NAV differs from exchange snapshot", "runbook:ledger"),
    ("execution-gateway", "slippage heartbeat feature drift uncertain cause", "runbook:drift"),
]


QUERY_AWARE_QUERIES = [
    ("execution-gateway", "HTTP 429 retry-after throttling", "runbook:throttle"),
    ("market-feed", "WebSocket feed connection lost", "runbook:feed"),
    ("execution-gateway", "SQL query duration backlog", "runbook:slow-sql"),
    ("execution-gateway", "Retained memory buffers growing", "runbook:memory"),
    ("execution-gateway", "Routing regression after deployment", "runbook:deploy"),
    ("portfolio-ledger", "Local NAV differs from exchange", "runbook:ledger"),
    ("execution-gateway", "Slippage and heartbeat drift", "runbook:drift"),
]
UNRELATED_QUERIES = [
    ("execution-gateway", "Banana bread recipe with cinnamon"),
    ("market-feed", "Lunar crater cartography telescope"),
    ("portfolio-ledger", "Ceramic pottery kiln glazing"),
]


def measure(store, queries, method):
    rows = []
    for service, query, expected in queries:
        hits = store.search(service=service, query=query, method=method, limit=3)
        rank = next((i for i, h in enumerate(hits, 1) if h["document_id"] == expected), 0)
        rows.append(
            {"service": service, "query": query, "expected": expected, "rank": rank, "hits": hits}
        )
    return {
        "queries": len(rows),
        "recall_at_3": sum(bool(r["rank"]) for r in rows) / len(rows),
        "mrr": sum(1 / r["rank"] if r["rank"] else 0 for r in rows) / len(rows),
        "rows": rows,
    }


def main():
    results, targeted, unrelated = {}, {}, {}
    with tempfile.TemporaryDirectory() as directory:
        db = Database(f"sqlite:///{directory}/knowledge.db")
        db.initialize()
        try:
            store = Knowledge(db, "hash")  # Explicitly offline, regardless of application settings.
            store.seed()
            for method in ("keyword", "vector"):
                baseline = measure(store, QUERIES, method)
                results[method] = {k: v for k, v in baseline.items() if k != "rows"}
                targeted[method] = measure(store, QUERY_AWARE_QUERIES, method)
                unrelated[method] = [
                    {
                        "service": service,
                        "query": query,
                        "hits": store.search(service=service, query=query, method=method, limit=3),
                    }
                    for service, query in UNRELATED_QUERIES
                ]
        finally:
            db.engine.dispose()
    print(
        json.dumps(
            {
                "benchmark": "runbook-seed-1",
                "embedding": "hash-word12-768-v1",
                "root_cause_gain": None,
                "results": results,
                "query_aware_results": targeted,
                "unrelated_queries": unrelated,
                "score_note": "Scores are uncalibrated similarity, not relevance probabilities. Nonzero hits may be unrelated.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
