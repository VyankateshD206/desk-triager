# Versioned retrieval and schema migrations

The agent's `search_runbooks` tool retrieves reviewed runbooks and manually indexed past
incidents within the incident service. Documents carry immutable versions, chunk IDs,
source references, and an embedding version. Superseded document versions remain auditable
but are not retrieved. The importer rejects unreviewed or evaluation-split documents.

## Query-aware agent tool

The only argument-bearing investigation tool is now:

```json
{"name": "search_runbooks", "args": {"query": "HTTP 429 Retry-After throttling"}}
```

`SearchRunbooksArgs` requires exactly one string property, `query`. Leading/trailing spaces
are trimmed, then length must be 3–160 characters. Newlines and Unicode control/format
characters are rejected before trimming. Empty strings, nonstrings and extra properties are
blocked. For example, `{}`, `{"query": 429}`, and
`{"query": "HTTP 429", "service": "market-feed"}` are invalid calls.

The model is asked to search only when reviewed operational guidance could clarify an
unresolved symptom or suspected cause, using observed symptoms, error codes and subsystem
terms. Retrieval is optional; the instruction does not require a search on every incident.
No expected evaluation answers are supplied to the model.

The graph validates arguments before dispatch and passes only the normalized query. The
trusted incident service is captured by the tool closure, with `method="vector"` and
`limit=3`. The model cannot choose service, database, embedding provider, method, limit,
endpoints, SQL or recovery actions. Operator search APIs still support keyword comparison;
that capability is not exposed to the agent. All other investigation tools still require
empty arguments. Unknown tools or invalid arguments return a safe blocked outcome without
executing. Attempts consume the existing tool budget; the round budget and deadline remain enforced. Tool dispatch rechecks the deadline after
planning, so an expired plan cannot begin a runbook search.
One successful runbook search is allowed per investigation: further successful-name calls
are duplicates, even with a different query. Failed attempts retain the existing retry/budget
behavior; no repeated-search orchestration is added.

Queries are redacted by the existing untrusted-input/sanitization boundary before persistence
or display, including configured credentials and common secret assignments. Tool events
retain the normalized query, trusted service, status, latency and returned evidence IDs.
Successful retrieval events additionally retain document ID, version, chunk ID, source and
embedding version independently of the bounded preview. Full sanitized documents remain in
the evidence record. Retrieved text remains evidence, not instructions or execution authority.

Gemini receives the existing uppercase OBJECT/STRING declaration with required `query`.
The existing OpenAI schema translator recursively converts it to object/string while
preserving required properties. Both HTTP adapters and their call/result envelopes remain
unchanged. Runtime validation enforces the strict contract regardless of provider behavior.

`FixtureAgent` uses the same argument contract, graph validator and fixed search options.
Its predictor receives only fixture inputs and the model query, not scoring labels or
postmortem answers. Corpus families and train/test splits are unchanged; only reviewed,
active, matching-version knowledge is searched.

Compatibility: old zero-argument `search_runbooks()` calls are now blocked. Direct callers
must provide `query`; older pending zero-argument calls in resumed investigations follow
the same blocked-attempt/budget path. No stored records or checkpoints are migrated.

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

The runner is explicitly offline (`Knowledge(..., "hash")`) and reports the original seven
queries, seven targeted queries, and three unrelated probes for keyword and hashed-vector
retrieval. It prints returned document IDs, versions, ranks and raw similarity scores, so
misses and nonzero unrelated hits remain visible. No Gemini benchmark is run by this command.

Measured on 24 October 2026, using unchanged repository runbooks:

| Targeted query | Expected document | Vector rank | Vector score |
| --- | --- | ---: | ---: |
| HTTP 429 retry-after throttling | runbook:throttle | 1 | 0.3665 |
| WebSocket feed connection lost | runbook:feed | 1 | 0.1309 |
| SQL query duration backlog | runbook:slow-sql | 1 | 0.4006 |
| Retained memory buffers growing | runbook:memory | 1 | 0.3205 |
| Routing regression after deployment | runbook:deploy | 1 | 0.3694 |
| Local NAV differs from exchange | runbook:ledger | 1 | 0.1280 |
| Slippage and heartbeat drift | runbook:drift | 1 | 0.3981 |

Original and targeted suites each achieve recall@3 **1.00** and MRR **1.00** for both methods.
This small seven-document seed comparison shows no advantage for vectors and does not
establish a diagnosis/root-cause accuracy gain. Feed and ledger scopes each have one seeded
runbook, so their rankings are especially limited evidence of retrieval quality.

Unrelated probes demonstrate the limitation: vector search returns nonzero hits for 2/3,
including banana bread → memory (0.1060) and pottery → ledger (0.0484). Lunar cartography
returns none. Keyword search returns hits for 1/3 (banana bread query, 0.2000). These are raw,
uncalibrated similarities, not probabilities or verified relevance. No confidence threshold,
semantic reranker, query expansion, or automatic abstention filter was added. The existing
positive-score filter and service boundary remain unchanged. The incident benchmark must
still measure retrieval's effect on diagnosis before claiming that RAG improves accuracy.

Validation uses mocked Gemini/OpenAI HTTP responses with the real LangGraph, local hashing
and reviewed runbooks. It covers contract validation, query use, service isolation, rejected
extra arguments, disabled retrieval, duplicate calls, provenance, secret redaction, parameterless
tools and bounded safe fallback on failures. Final checks: workflow **41 passed**, retrieval
**42 passed**, full `make test` **250 passed**, and `make build` passed (lint, frontend checks,
wheel and packaged assets). No paid model/embedding calls were made.

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
