"""Index an explicitly reviewed knowledge JSON document; never eval fixture files."""

import argparse
import json
from pathlib import Path

from .config import Settings
from .contracts import Contract
from .db import Database
from .retrieval import Knowledge


class Document(Contract):
    document_id: str
    version: str
    service: str
    title: str
    content: str
    source: str


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--reviewed", action="store_true", required=True)
    args = parser.parse_args()
    document = Document.model_validate(json.loads(args.document.read_text()))
    settings = Settings()
    db = Database(settings.database_url)
    try:
        db.initialize()
        Knowledge(db, settings.embedding_provider).add(
            **document.model_dump(), reviewed=args.reviewed
        )
        print("Indexed reviewed knowledge version.")
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
