import pytest
from sqlalchemy import inspect, text

from evals.retrieval import QUERY_AWARE_QUERIES
from triager.db import Database
from triager.retrieval import Knowledge


@pytest.fixture
def knowledge(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    db.initialize()
    knowledge = Knowledge(db)
    knowledge.seed()
    yield knowledge
    db.engine.dispose()


def test_vector_search_is_scoped_and_has_provenance(knowledge):
    hits = knowledge.search("execution-gateway", "slow SQL query database duration")
    assert hits[0]["document_id"] == "runbook:slow-sql"
    assert all(hit["source"] and hit["version"] and hit["chunk_id"] for hit in hits)
    assert not knowledge.search("market-feed", "SQL query memory")[0:1] or all(
        hit["document_id"] == "runbook:feed"
        for hit in knowledge.search("market-feed", "SQL query memory")
    )
    assert knowledge.search("market-feed", "") == []


def test_retrieval_excludes_unreviewed_and_evaluation_documents(knowledge):
    document = dict(
        document_id="incident:1",
        version="1",
        service="execution-gateway",
        title="Incident",
        content="A manually reviewed incident",
        source="review:1",
    )
    with pytest.raises(ValueError):
        knowledge.add(**document)
    with pytest.raises(ValueError):
        knowledge.add(**document, reviewed=True, split="test")
    knowledge.add(**document, reviewed=True)
    assert any(
        h["document_id"] == "incident:1"
        for h in knowledge.search("execution-gateway", "manually reviewed incident")
    )


def test_versions_are_immutable_and_superseded_chunks_not_retrieved(knowledge):
    document = dict(
        document_id="incident:2",
        version="1",
        service="execution-gateway",
        title="Buffer incident",
        content="retained buffers cause memory pressure",
        source="review:2",
        reviewed=True,
    )
    knowledge.add(**document)
    knowledge.add(**document)
    with pytest.raises(ValueError, match="immutable"):
        knowledge.add(**{**document, "content": "A changed diagnosis"})
    knowledge.add(**{**document, "version": "2", "content": "Corrected buffer retention diagnosis"})
    assert all(
        h["version"] == "2"
        for h in knowledge.search("execution-gateway", "buffer retention")
        if h["document_id"] == "incident:2"
    )


def test_migration_adopts_existing_sql_without_erasing_rows(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/legacy.db")
    with db.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE service_watermarks (service VARCHAR PRIMARY KEY, "
                "event_timestamp VARCHAR NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO service_watermarks VALUES ('market-feed', 'original')")
        )
    db.initialize()
    db.initialize()
    with db.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT event_timestamp FROM service_watermarks")).scalar()
            == "original"
        )
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0001_schema"
        )
        assert "recovery_jobs" in inspect(connection).get_table_names()
    db.engine.dispose()


def test_failed_embedding_does_not_publish_partial_version(tmp_path, monkeypatch):
    from sqlalchemy import select

    from triager.db import Database
    from triager.models import KnowledgeChunk
    from triager.retrieval import Knowledge

    db = Database(f"sqlite:///{tmp_path}/atomic.db")
    db.initialize()
    calls = []

    def broken(*args):
        calls.append(1)
        if len(calls) > 1:
            raise TimeoutError("embedding unavailable")
        return [0.0] * 768

    monkeypatch.setattr("triager.retrieval.embed", broken)
    with pytest.raises(TimeoutError):
        Knowledge(db).add(
            document_id="long",
            version="1",
            service="market-feed",
            title="Long",
            content="x" * 3000,
            source="test",
            reviewed=True,
        )
    with db.Session() as session:
        assert session.scalar(select(KnowledgeChunk)) is None
    db.engine.dispose()


@pytest.mark.parametrize(
    "query", ["RAG", "HTTP 429", "  HTTP 429 Retry-After throttling  ", "a" * 160]
)
def test_search_query_contract_normalizes_strings(query):
    from triager.contracts import SearchRunbooksArgs

    assert SearchRunbooksArgs(query=query).query == query.strip()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": ""},
        {"query": "  "},
        {"query": "ab"},
        {"query": "x" * 161},
        {"query": 429},
        {"query": True},
        {"query": None},
        {"query": ["rate limit"]},
        {"query": {"$ne": None}},
        {"query": b"HTTP 429"},
        {"query": "HTTP 429", "service": "market-feed"},
        {"query": "HTTP 429", "limit": 100},
        {"query": "HTTP 429", "method": "keyword"},
        {"query": "HTTP 429", "database_url": "untrusted"},
        {"query": "HTTP\n429"},
        {"query": "HTTP\r429"},
        {"query": "HTTP\t429"},
        {"query": "\nHTTP 429"},
        {"query": "HTTP 429\x00"},
        {"query": "HTTP 429\x7f"},
        {"query": "HTTP\u0085429"},
        {"query": "HTTP\u2028429"},
        {"query": "HTTP\u202e429"},
    ],
)
def test_search_query_contract_rejects_invalid_arguments(arguments):
    from pydantic import ValidationError

    from triager.contracts import SearchRunbooksArgs

    with pytest.raises(ValidationError):
        SearchRunbooksArgs.model_validate(arguments)


@pytest.mark.parametrize("service,query,expected", QUERY_AWARE_QUERIES)
def test_incident_specific_queries_retrieve_expected_top_three(knowledge, service, query, expected):
    hits = knowledge.search(service=service, query=query, method="vector", limit=3)
    assert expected in [h["document_id"] for h in hits]
    assert len(hits) <= 3
    assert all(h["version"] and h["source"] and h["embedding_version"] for h in hits)


def test_unrelated_query_scores_are_reported_not_treated_as_probabilities(knowledge):
    from evals.retrieval import UNRELATED_QUERIES

    for service, query in UNRELATED_QUERIES:
        hits = knowledge.search(service, query, method="vector", limit=3)
        # Lexical collisions/overlap may produce nonzero hits; do not impose a confidence cutoff.
        assert all(0 < h["score"] <= 1.000001 for h in hits)
        assert all(h["document_id"] == "runbook:feed" for h in hits if service == "market-feed")
        assert all(
            h["document_id"] == "runbook:ledger" for h in hits if service == "portfolio-ledger"
        )


def test_production_and_fixture_use_the_same_query_and_trusted_search_options(
    knowledge, tmp_path, monkeypatch
):
    from dataclasses import replace

    from pydantic import ValidationError

    from evals.benchmark import FixtureAgent
    from triager.agent import TriageAgent
    from triager.config import Settings

    settings = Settings(ai_provider="offline", embedding_provider="hash", retrieval_enabled=True)
    inputs = {"service": "execution-gateway", "tools": {}, "evidence": []}
    fixture = FixtureAgent(settings, inputs, str(tmp_path / "fixture.graph"), knowledge)
    production = TriageAgent(knowledge.db, settings)
    production.inspect = lambda _: pytest.fail(
        "Retrieval must use the supplied query, not recent logs"
    )
    original = Knowledge.search
    searches = []

    def search(self, **kwargs):
        searches.append(kwargs)
        return original(self, **kwargs)

    monkeypatch.setattr(Knowledge, "search", search)
    results = []
    for agent in (production, fixture):
        tool = agent.tools("execution-gateway")["search_runbooks"]
        results.append(tool(query="  HTTP 429 retry-after throttling  "))
        with pytest.raises(ValidationError):
            tool(query=429)
        with pytest.raises(TypeError):
            tool(query="HTTP 429", service="market-feed")
    assert results[0] == results[1]
    assert (
        searches
        == [
            {
                "service": "execution-gateway",
                "query": "HTTP 429 retry-after throttling",
                "method": "vector",
                "limit": 3,
            }
        ]
        * 2
    )
    with pytest.raises(ValueError, match="scope"):
        fixture.tools("market-feed")
    fixture.settings = replace(settings, retrieval_enabled=False)
    assert "search_runbooks" not in fixture.tools("execution-gateway")
