"""Adopt the legacy schema and create missing tables without altering existing data.

This baseline freezes DDL at v1.6.0; later schema changes must use new revisions.
"""

from alembic import op
from sqlalchemy import inspect

revision = "0001_schema"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = {
    "postgresql": [
        (
            "audit",
            "\n"
            "CREATE TABLE audit (\n"
            "\tid SERIAL NOT NULL, \n"
            "\tat VARCHAR NOT NULL, \n"
            "\tincident_id VARCHAR NOT NULL, \n"
            "\tactor VARCHAR NOT NULL, \n"
            "\taction VARCHAR NOT NULL, \n"
            "\tdetail JSON NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "balances",
            "\n"
            "CREATE TABLE balances (\n"
            "\taccount VARCHAR NOT NULL, \n"
            "\tlocal_nav NUMERIC(20, 2) NOT NULL, \n"
            "\texchange_nav NUMERIC(20, 2) NOT NULL, \n"
            "\tPRIMARY KEY (account)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "incidents",
            "\n"
            "CREATE TABLE incidents (\n"
            "\tid VARCHAR NOT NULL, \n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tkind VARCHAR NOT NULL, \n"
            "\tstatus VARCHAR NOT NULL, \n"
            "\topened_at VARCHAR NOT NULL, \n"
            "\tupdated_at VARCHAR NOT NULL, \n"
            "\tevidence JSON NOT NULL, \n"
            "\tdiagnosis TEXT NOT NULL, \n"
            "\taction VARCHAR NOT NULL, \n"
            "\toccurrences INTEGER NOT NULL, \n"
            "\treport TEXT NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "knowledge_chunks",
            "\n"
            "CREATE TABLE knowledge_chunks (\n"
            "\tid VARCHAR(64) NOT NULL, \n"
            "\tdocument_id VARCHAR NOT NULL, \n"
            "\tdocument_version VARCHAR NOT NULL, \n"
            "\tservice VARCHAR NOT NULL, \n"
            "\ttitle VARCHAR NOT NULL, \n"
            "\tcontent TEXT NOT NULL, \n"
            "\tsource VARCHAR NOT NULL, \n"
            "\tembedding_version VARCHAR NOT NULL, \n"
            "\tembedding public.VECTOR(768) NOT NULL, \n"
            "\tactive BOOLEAN NOT NULL, \n"
            "\tcreated_at VARCHAR NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_service ON knowledge_chunks "
                "(service)",
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_document_id ON knowledge_chunks "
                "(document_id)",
            ],
        ),
        (
            "recovery_jobs",
            "\n"
            "CREATE TABLE recovery_jobs (\n"
            "\tid VARCHAR NOT NULL, \n"
            "\tproposal_id VARCHAR NOT NULL, \n"
            "\tincident_id VARCHAR NOT NULL, \n"
            "\tkey_hash VARCHAR(64) NOT NULL, \n"
            "\trequest_hash VARCHAR(64) NOT NULL, \n"
            "\tactor VARCHAR(80) NOT NULL, \n"
            "\treason TEXT NOT NULL, \n"
            "\tdecision VARCHAR NOT NULL, \n"
            "\tstatus VARCHAR NOT NULL, \n"
            "\tcreated_at VARCHAR NOT NULL, \n"
            "\tlease_until VARCHAR, \n"
            "\tlease_token VARCHAR, \n"
            "\tattempts INTEGER NOT NULL, \n"
            "\tresult JSON NOT NULL, \n"
            "\tverification_deadline VARCHAR, \n"
            "\thealthy_samples INTEGER NOT NULL, \n"
            "\tPRIMARY KEY (id), \n"
            "\tUNIQUE (proposal_id), \n"
            "\tUNIQUE (key_hash)\n"
            ")\n"
            "\n",
            [
                "CREATE INDEX IF NOT EXISTS ix_recovery_jobs_incident_id ON recovery_jobs "
                "(incident_id)",
                "CREATE INDEX IF NOT EXISTS ix_recovery_jobs_status ON recovery_jobs (status)",
            ],
        ),
        (
            "recovery_proposals",
            "\n"
            "CREATE TABLE recovery_proposals (\n"
            "\tid VARCHAR NOT NULL, \n"
            "\tincident_id VARCHAR NOT NULL, \n"
            "\tfingerprint VARCHAR(64) NOT NULL, \n"
            "\tcreated_at VARCHAR NOT NULL, \n"
            "\tstatus VARCHAR NOT NULL, \n"
            "\tpayload JSON NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [
                "CREATE INDEX IF NOT EXISTS ix_recovery_proposals_incident_id ON "
                "recovery_proposals (incident_id)"
            ],
        ),
        (
            "service_watermarks",
            "\n"
            "CREATE TABLE service_watermarks (\n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tevent_timestamp VARCHAR NOT NULL, \n"
            "\tPRIMARY KEY (service)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "simulator_faults",
            "\n"
            "CREATE TABLE simulator_faults (\n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tkind VARCHAR NOT NULL, \n"
            "\tgeneration VARCHAR NOT NULL, \n"
            "\tPRIMARY KEY (service)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "telemetry",
            "\n"
            "CREATE TABLE telemetry (\n"
            "\tid VARCHAR(80) NOT NULL, \n"
            "\treceived_at VARCHAR NOT NULL, \n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tpayload JSON NOT NULL, \n"
            "\tscore NUMERIC(12, 6) NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            ["CREATE INDEX IF NOT EXISTS ix_telemetry_service ON telemetry (service)"],
        ),
    ],
    "sqlite": [
        (
            "audit",
            "\n"
            "CREATE TABLE audit (\n"
            "\tid INTEGER NOT NULL, \n"
            "\tat VARCHAR NOT NULL, \n"
            "\tincident_id VARCHAR NOT NULL, \n"
            "\tactor VARCHAR NOT NULL, \n"
            "\taction VARCHAR NOT NULL, \n"
            "\tdetail JSON NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "balances",
            "\n"
            "CREATE TABLE balances (\n"
            "\taccount VARCHAR NOT NULL, \n"
            "\tlocal_nav NUMERIC(20, 2) NOT NULL, \n"
            "\texchange_nav NUMERIC(20, 2) NOT NULL, \n"
            "\tPRIMARY KEY (account)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "incidents",
            "\n"
            "CREATE TABLE incidents (\n"
            "\tid VARCHAR NOT NULL, \n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tkind VARCHAR NOT NULL, \n"
            "\tstatus VARCHAR NOT NULL, \n"
            "\topened_at VARCHAR NOT NULL, \n"
            "\tupdated_at VARCHAR NOT NULL, \n"
            "\tevidence JSON NOT NULL, \n"
            "\tdiagnosis TEXT NOT NULL, \n"
            "\taction VARCHAR NOT NULL, \n"
            "\toccurrences INTEGER NOT NULL, \n"
            "\treport TEXT NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "knowledge_chunks",
            "\n"
            "CREATE TABLE knowledge_chunks (\n"
            "\tid VARCHAR(64) NOT NULL, \n"
            "\tdocument_id VARCHAR NOT NULL, \n"
            "\tdocument_version VARCHAR NOT NULL, \n"
            "\tservice VARCHAR NOT NULL, \n"
            "\ttitle VARCHAR NOT NULL, \n"
            "\tcontent TEXT NOT NULL, \n"
            "\tsource VARCHAR NOT NULL, \n"
            "\tembedding_version VARCHAR NOT NULL, \n"
            "\tembedding JSON NOT NULL, \n"
            "\tactive BOOLEAN NOT NULL, \n"
            "\tcreated_at VARCHAR NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_service ON knowledge_chunks "
                "(service)",
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_document_id ON knowledge_chunks "
                "(document_id)",
            ],
        ),
        (
            "recovery_jobs",
            "\n"
            "CREATE TABLE recovery_jobs (\n"
            "\tid VARCHAR NOT NULL, \n"
            "\tproposal_id VARCHAR NOT NULL, \n"
            "\tincident_id VARCHAR NOT NULL, \n"
            "\tkey_hash VARCHAR(64) NOT NULL, \n"
            "\trequest_hash VARCHAR(64) NOT NULL, \n"
            "\tactor VARCHAR(80) NOT NULL, \n"
            "\treason TEXT NOT NULL, \n"
            "\tdecision VARCHAR NOT NULL, \n"
            "\tstatus VARCHAR NOT NULL, \n"
            "\tcreated_at VARCHAR NOT NULL, \n"
            "\tlease_until VARCHAR, \n"
            "\tlease_token VARCHAR, \n"
            "\tattempts INTEGER NOT NULL, \n"
            "\tresult JSON NOT NULL, \n"
            "\tverification_deadline VARCHAR, \n"
            "\thealthy_samples INTEGER NOT NULL, \n"
            "\tPRIMARY KEY (id), \n"
            "\tUNIQUE (proposal_id), \n"
            "\tUNIQUE (key_hash)\n"
            ")\n"
            "\n",
            [
                "CREATE INDEX IF NOT EXISTS ix_recovery_jobs_incident_id ON recovery_jobs "
                "(incident_id)",
                "CREATE INDEX IF NOT EXISTS ix_recovery_jobs_status ON recovery_jobs (status)",
            ],
        ),
        (
            "recovery_proposals",
            "\n"
            "CREATE TABLE recovery_proposals (\n"
            "\tid VARCHAR NOT NULL, \n"
            "\tincident_id VARCHAR NOT NULL, \n"
            "\tfingerprint VARCHAR(64) NOT NULL, \n"
            "\tcreated_at VARCHAR NOT NULL, \n"
            "\tstatus VARCHAR NOT NULL, \n"
            "\tpayload JSON NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            [
                "CREATE INDEX IF NOT EXISTS ix_recovery_proposals_incident_id ON recovery_proposals "
                "(incident_id)"
            ],
        ),
        (
            "service_watermarks",
            "\n"
            "CREATE TABLE service_watermarks (\n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tevent_timestamp VARCHAR NOT NULL, \n"
            "\tPRIMARY KEY (service)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "simulator_faults",
            "\n"
            "CREATE TABLE simulator_faults (\n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tkind VARCHAR NOT NULL, \n"
            "\tgeneration VARCHAR NOT NULL, \n"
            "\tPRIMARY KEY (service)\n"
            ")\n"
            "\n",
            [],
        ),
        (
            "telemetry",
            "\n"
            "CREATE TABLE telemetry (\n"
            "\tid VARCHAR(80) NOT NULL, \n"
            "\treceived_at VARCHAR NOT NULL, \n"
            "\tservice VARCHAR NOT NULL, \n"
            "\tpayload JSON NOT NULL, \n"
            "\tscore NUMERIC(12, 6) NOT NULL, \n"
            "\tPRIMARY KEY (id)\n"
            ")\n"
            "\n",
            ["CREATE INDEX IF NOT EXISTS ix_telemetry_service ON telemetry (service)"],
        ),
    ],
}


def upgrade():
    connection = op.get_bind()
    present = set(inspect(connection).get_table_names())
    for name, ddl, indexes in SCHEMA[connection.dialect.name]:
        if name not in present:
            op.execute(ddl)
        for statement in indexes:
            op.execute(statement)


def downgrade():
    raise RuntimeError("Baseline adoption is irreversible; restore a reviewed database backup")
