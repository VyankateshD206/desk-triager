"""Versioned runbook retrieval: local hashed vectors or optional Gemini embeddings."""

import json
import os
import re

import httpx
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sqlalchemy import Float, cast, select

from .models import KnowledgeChunk, PublicVector, now
from .recovery import digest
from .security import redact_text

DIMENSIONS = 768


def embed(text, provider="hash", task="RETRIEVAL_DOCUMENT"):
    text = redact_text(text)
    if provider == "hash":
        # Lexical vector baseline, not a semantic language model embedding.
        return (
            HashingVectorizer(
                n_features=DIMENSIONS, alternate_sign=False, ngram_range=(1, 2), norm="l2"
            )
            .transform([text])
            .toarray()[0]
            .tolist()
        )
    if provider != "gemini":
        raise ValueError("Unknown embedding provider")
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("Embedding API key missing")
    with httpx.Client(timeout=10) as client:
        response = client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-embedding-001:embedContent",
            headers={"x-goog-api-key": key},
            json={
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": text}]},
                "taskType": task,
                "outputDimensionality": DIMENSIONS,
            },
        )
        response.raise_for_status()
        vector = np.asarray(response.json()["embedding"]["values"], dtype=float)
        if (
            vector.shape != (DIMENSIONS,)
            or not np.all(np.isfinite(vector))
            or np.linalg.norm(vector) == 0
        ):
            raise ValueError("Invalid embedding")
        return (vector / np.linalg.norm(vector)).tolist()


class Knowledge:
    def __init__(self, database, provider="hash"):
        self.db, self.provider = database, provider
        self.version = "hash-word12-768-v1" if provider == "hash" else "gemini-embedding-001-768-v1"

    def add(
        self,
        *,
        document_id,
        version,
        service,
        title,
        content,
        source,
        split="knowledge",
        reviewed=False,
    ):
        if not reviewed or split != "knowledge":
            raise ValueError("Only reviewed knowledge documents may enter retrieval")
        if service not in {"market-feed", "execution-gateway", "portfolio-ledger"}:
            raise ValueError("Unknown knowledge service")
        title, content, source = map(redact_text, (title, content, source))
        if not content.strip() or not document_id or not version:
            raise ValueError("Knowledge needs a document ID, version, and content")
        chunks = [content[i : i + 1600] for i in range(0, len(content), 1400)]
        identifiers = {
            digest([document_id, version, index, chunk, self.version])
            for index, chunk in enumerate(chunks)
        }
        with self.db.Session() as session:
            existing = set(
                session.scalars(
                    select(KnowledgeChunk.id).where(
                        KnowledgeChunk.document_id == document_id,
                        KnowledgeChunk.document_version == version,
                        KnowledgeChunk.embedding_version == self.version,
                    )
                )
            )
            if existing and existing != identifiers:
                raise ValueError("Document versions are immutable; increment the version")
        for index, chunk in enumerate(chunks):
            chunk_id = digest([document_id, version, index, chunk, self.version])
            with self.db.Session() as session:
                if session.get(KnowledgeChunk, chunk_id):
                    continue
            vector = embed(title + "\n" + chunk, self.provider)
            with self.db.Session.begin() as session:
                # Superseded versions remain auditable but are excluded from search.
                from sqlalchemy import update

                session.execute(
                    update(KnowledgeChunk)
                    .where(
                        KnowledgeChunk.document_id == document_id,
                        KnowledgeChunk.document_version != version,
                    )
                    .values(active=False)
                )
                session.add(
                    KnowledgeChunk(
                        id=chunk_id,
                        document_id=document_id,
                        document_version=version,
                        service=service,
                        title=title,
                        content=chunk,
                        source=source,
                        embedding_version=self.version,
                        embedding=vector,
                        active=True,
                        created_at=now(),
                    )
                )

    def search(self, service, query, *, method="vector", limit=3):
        if service not in {"market-feed", "execution-gateway", "portfolio-ledger"}:
            raise ValueError("Unknown knowledge scope")
        limit = min(max(limit, 1), 5)
        query = redact_text(query)[:2000]
        with self.db.Session() as session:
            statement = select(KnowledgeChunk).where(
                KnowledgeChunk.service == service,
                KnowledgeChunk.active.is_(True),
                KnowledgeChunk.embedding_version == self.version,
            )
            if method == "vector":
                vector = embed(query, self.provider, "RETRIEVAL_QUERY")
                if not np.any(vector):
                    return []
                if self.db.engine.dialect.name == "postgresql":
                    distance = KnowledgeChunk.embedding.op(
                        "OPERATOR(public.<=>)", return_type=Float
                    )(cast(vector, PublicVector(DIMENSIONS)))
                    found = session.execute(
                        statement.add_columns(distance).order_by(distance).limit(limit)
                    ).all()
                    ranked = [(row, 1 - float(score)) for row, score in found]
                else:
                    rows = session.scalars(statement).all()
                    ranked = sorted(
                        ((row, float(np.dot(row.embedding, vector))) for row in rows),
                        key=lambda item: (-item[1], item[0].id),
                    )[:limit]
            elif method == "keyword":
                tokens = set(re.findall(r"\w+", query.lower()))
                rows = session.scalars(statement).all()
                ranked = sorted(
                    (
                        (
                            row,
                            len(
                                tokens
                                & set(re.findall(r"\w+", (row.title + " " + row.content).lower()))
                            )
                            / max(1, len(tokens)),
                        )
                        for row in rows
                    ),
                    key=lambda item: (-item[1], item[0].id),
                )[:limit]
            else:
                raise ValueError("Unknown retrieval method")
            return [
                {
                    "document_id": row.document_id,
                    "version": row.document_version,
                    "chunk_id": row.id,
                    "title": row.title,
                    "content": row.content,
                    "source": row.source,
                    "score": score,
                    "embedding_version": self.version,
                }
                for row, score in ranked
                if score > 0
            ]

    def seed(self):
        from importlib.resources import files

        documents = json.loads(files("triager").joinpath("knowledge/runbooks.json").read_text())
        for document in documents:
            self.add(**document, reviewed=True)
