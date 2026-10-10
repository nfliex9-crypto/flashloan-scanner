"""Schema probe is observational and cannot authorize any broker or Paper order."""
from aegis import stream_probe


class Cursor:
    def __init__(self):
        self.sql=[]
        self.last=""
        self.args=()
    def execute(self,sql,args=None):
        self.sql.append(sql)
        self.last=sql
        self.args=args
        assert not any(" "+verb+" " in " "+sql.upper()+" " for verb in
                       ("INSERT","UPDATE","DELETE","CREATE","ALTER","DROP","TRUNCATE"))
    def fetchone(self):
        sql=self.last
        if "to_regclass(%s) AS rel" in sql:return {"rel":"aegis."+self.args[0].split(".")[-1]}
        if "information_schema.columns" in sql:return {"found":True}
        if "has_table_privilege" in sql:return {"allowed":True}
        if "pg_get_constraintdef" in sql:
            return {"definition":"CHECK(interval_minutes IN (1,5,15,60,240,1440,10080))"}
        if "count(*) AS n FROM aegis.stream_accounts" in sql:return {"n":3}
        raise AssertionError(sql)
    def fetchall(self):
        if "stream_bar_ledger WHERE" in self.last:return [{"interval_minutes":1,"n":30,"latest":None}]
        if "stream_decisions WHERE" in self.last:return []
        raise AssertionError(self.last)


def test_probe_identifies_undocumented_no_trade_diagnosis_without_writes():
    cur=Cursor()
    r=stream_probe.inspect(cur)
    assert r["ok"] is True
    assert r["mode"]=="READ_ONLY_STREAM_STORAGE_PROBE"
    assert r["short_account_count"]==3
    assert r["recent_bar_ledger"][0]["n"]==30
    assert r["recent_decisions"]==[]
    assert all(x["seven_intervals_supported"] for x in r["interval_constraints"].values())
    assert r["actions_disabled"] is True
    assert len(cur.sql)>20
