"""Railway market worker never needs DDL or production broker privileges."""
import pytest
from aegis.stream_schema import verify,REQUIRED_TABLE_PRIVILEGES,INTERVAL_TABLES


class FakeCursor:
    def __init__(self,missing_table=None,missing_privilege=None,old_constraint=None):
        self.missing_table=missing_table
        self.missing_privilege=missing_privilege
        self.old_constraint=old_constraint
        self.queries=[]
        self.last=None
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,args):
        self.queries.append((sql,args))
        if "to_regclass(%s) AS present" in sql:
            self.last={"present":None if args[0]==self.missing_table else args[0]}
        elif "has_table_privilege(" in sql:
            self.last={"allowed":tuple(args)!=self.missing_privilege}
        elif "pg_get_constraintdef" in sql:
            self.last={"definition":"CHECK (interval_minutes = ANY (ARRAY[1,5,15]))"
                if args[0]==self.old_constraint else
                "CHECK (interval_minutes = ANY (ARRAY[1,5,15,60,240,1440,10080]))"}
        else:
            raise AssertionError("Unexpected or unsafe startup SQL: "+sql)
    def fetchone(self):return self.last


class FakeConnection:
    def __init__(self,**kw):self.cur=FakeCursor(**kw)
    def cursor(self):return self.cur


def test_schema_verifier_requires_no_create_alter_drop_or_orders():
    db=FakeConnection()
    proof=verify(db)
    assert proof["mode"]=="READ_ONLY_SCHEMA_VERIFICATION"
    assert proof["verified_tables"]==len(REQUIRED_TABLE_PRIVILEGES)
    assert len([x for x,_ in db.cur.queries if "pg_get_constraintdef" in x])==len(INTERVAL_TABLES)
    assert all(x.startswith("SELECT ") for x,_ in db.cur.queries)
    assert all("aegis.paper_" not in repr(args) for _,args in db.cur.queries)


def test_schema_verifier_fails_on_missing_receipts_table():
    db=FakeConnection(missing_table="aegis.stream_historical_screens")
    with pytest.raises(RuntimeError,match="migration missing"):
        verify(db)


def test_schema_verifier_fails_on_missing_insert_grant():
    db=FakeConnection(missing_privilege=("aegis.stream_decisions","INSERT"))
    with pytest.raises(RuntimeError,match="privilege missing"):
        verify(db)


def test_schema_verifier_fails_if_weekly_migration_not_applied():
    db=FakeConnection(old_constraint="aegis.stream_accounts")
    with pytest.raises(RuntimeError,match="Seven-timeframe"):
        verify(db)
