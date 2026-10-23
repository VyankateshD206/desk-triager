# Versioned retrieval and schema migrations

The agent's `search_runbooks` tool retrieves reviewed runbooks and manually indexed past
incidents within the incident service. Documents carry immutable versions, chunk IDs,
source references, and an embedding version. Superseded document versions remain auditable
but are not retrieved. The importer rejects unreviewed or evaluation-split documents.

PostgreSQL uses pgvector cosine distance; SQLite uses the same vectors with an in-process
cosine comparison. Default `EMBEDDING_PROVIDER=hash` uses normalized 768-dimensional hashed
word/bigram features from scikit-learn. This is a lexical baseline, not a semantic language
model embedding. It runs without credentials, model downloads, or API charges.

For optional semantic embeddings, set `EMBEDDING_PROVIDER=gemini` and configure a Gemini key.
The adapter uses `gemini-embedding-001`, 768 dimensions, and retrieval query/document task
roles. This explicitly opts into embedding API calls while indexing and searching. Different
embedding versions are not mixed in a search. Set `RETRIEVAL_ENABLED=false` to disable the
tool and startup seeding. Seven reviewed, repository-authored runbooks seed the local store.

## Index a reviewed incident

Create a JSON document containing only `document_id`, `version`, `service`, `title`, `content`,
and `source`. Then run:

```bash
python -m triager.knowledge_cli reviewed-incident.json --reviewed
```

This is an operator workflow. Model tools cannot index documents or change knowledge.
Rejected recommendations must be reviewed before reuse. Evaluation fixtures and their
answer-bearing postmortems are not automatically indexed. Do not import held-out incident
answers or variants from the same incident family into the retrieval store.

## Measure retrieval

```bash
python -m evals.retrieval
```

On seven independently worded runbook queries, both keyword and hashed-vector retrieval
achieve recall@3 1.00 and MRR 1.00. This small seed comparison shows no advantage for vectors.
It does not establish a root-cause accuracy gain. The expanded incident benchmark compares
the graph with and without retrieval separately; report those results before claiming value.

## Database migrations

Startup now upgrades packaged Alembic revisions instead of relying on `create_all`.
Revision `0001_schema` freezes the application schema, adopts existing tables, creates
missing tables/indexes, and preserves existing rows. Future alterations require new
revisions. The baseline deliberately refuses destructive downgrade; restore a reviewed
backup rather than dropping application data.

PostgreSQL requires pgvector installed server-side and the `vector` extension in `public`.
The Docker demo uses `pgvector/pgvector:0.8.7-pg17`; a database role needs permission to
create the extension on first setup. SQLite needs no extension. CI verifies schema adoption,
version immutability, service scoping, real PostgreSQL vector search, and isolated recovery
schema behavior. Vector types and operators are schema-qualified to support that isolation.
