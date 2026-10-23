from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from .models import Balance


class Database:
    def __init__(self, url):
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://") :]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            **(
                {"connect_args": {"check_same_thread": False}}
                if url.startswith("sqlite")
                else {"connect_args": {"connect_timeout": 10}, "pool_size": 5, "max_overflow": 5}
            ),
        )
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self, seed=False):
        if self.engine.dialect.name == "postgresql":
            with self.engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        if seed:
            with self.Session.begin() as db:
                # Preserve balances from installations that used the original account identifier.
                legacy = db.get(Balance, "demo-desk")
                if legacy and not db.get(Balance, "desk-primary"):
                    legacy.account = "desk-primary"
                    db.flush()
                if not db.get(Balance, "desk-primary"):
                    db.add(
                        Balance(
                            account="desk-primary",
                            local_nav=Decimal("1000000.00"),
                            exchange_nav=Decimal("1000000.00"),
                        )
                    )

    def reconcile(self, session=None):
        if session is not None:
            return self._balances(session)
        with self.Session() as db:
            return self._balances(db)

    @staticmethod
    def _balances(db):
        return [
            {
                "account": b.account,
                "local_nav": str(b.local_nav),
                "exchange_nav": str(b.exchange_nav),
                "difference": str(b.local_nav - b.exchange_nav),
            }
            for b in db.scalars(select(Balance))
        ]
