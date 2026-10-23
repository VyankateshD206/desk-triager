import pytest
from sqlalchemy import inspect, text

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
