"""Explicit, transactional migration of the isolated stream research ledger."""
from pathlib import Path
import hashlib
from .stream_worker import _connect


def migrate(conn):
    root=Path(__file__).resolve().parent.parent/'sql'
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SELECT pg_advisory_xact_lock(10841010)")
            cur.execute("CREATE TABLE IF NOT EXISTS aegis.stream_schema_versions "
                        "(name TEXT PRIMARY KEY, digest TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            for name in ('008_short_micro_research.sql','009_stream_decision_journal.sql','010_horizon_research.sql'):
                sql=(root/name).read_text()
                digest=hashlib.sha256(sql.encode()).hexdigest()
                cur.execute("SELECT digest FROM aegis.stream_schema_versions WHERE name=%s",(name,))
                old=cur.fetchone()
                if old:
                    if old['digest']!=digest:raise RuntimeError('Applied stream migration checksum mismatch')
                    continue
                cur.execute(sql)
                cur.execute("INSERT INTO aegis.stream_schema_versions(name,digest) VALUES(%s,%s)",(name,digest))


if __name__=='__main__':
    with _connect() as conn:migrate(conn)
    print('Independent stream schema verified')
