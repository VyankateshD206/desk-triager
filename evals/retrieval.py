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


def main():
    results = {}
    with tempfile.TemporaryDirectory() as directory:
        db = Database(f"sqlite:///{directory}/knowledge.db")
        db.initialize()
        try:
            store = Knowledge(db)
            store.seed()
            for method in ("keyword", "vector"):
                ranks = []
                for service, query, expected in QUERIES:
                    hits = store.search(service, query, method=method)
                    ranks.append(
                        next(
                            (
                                index
                                for index, hit in enumerate(hits, 1)
                                if hit["document_id"] == expected
                            ),
                            0,
                        )
                    )
                results[method] = {
                    "queries": len(ranks),
                    "recall_at_3": sum(bool(r) for r in ranks) / len(ranks),
                    "mrr": sum(1 / r if r else 0 for r in ranks) / len(ranks),
                }
        finally:
            db.engine.dispose()
    print(
        json.dumps(
            {
                "benchmark": "runbook-seed-1",
                "embedding": "hash-word12-768-v1",
                "root_cause_gain": None,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
