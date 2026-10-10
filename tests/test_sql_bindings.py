"""Guard static SQL cursor.execute calls against psycopg placeholder mismatches.

A mismatched parameter count raises psycopg.ProgrammingError *client side*
without a PostgreSQL SQLSTATE, causing misleading generic 503s.
"""
from __future__ import annotations

import ast
from pathlib import Path

SOURCES=(
    "aegis/intrabar_guard.py",
    "aegis/forward_broker.py",
    "aegis/stream_paper.py",
    "aegis/shadow_broker.py",
    "aegis/stream_worker.py",
)


def static_placeholder_mismatches(filename:str)->list[tuple[int,int,int]]:
    content=Path(filename).read_text(encoding="utf-8")
    tree=ast.parse(content,filename=filename)
    invalid=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute):
            continue
        if node.func.attr!="execute" or len(node.args)<2:
            continue
        sql,values=node.args[:2]
        if not isinstance(sql,ast.Constant) or not isinstance(sql.value,str):
            continue
        if not isinstance(values,(ast.Tuple,ast.List)):
            continue
        expected=sql.value.count("%s")
        supplied=len(values.elts)
        if expected!=supplied:
            invalid.append((node.lineno,expected,supplied))
    return invalid


def test_static_sql_bindings_match_across_every_paper_engine():
    problems={path:static_placeholder_mismatches(path) for path in SOURCES}
    assert not any(problems.values()),f"SQL binding counts differ: {problems}"


def test_intrabar_shadow_close_has_exactly_nineteen_bound_values():
    src=Path("aegis/intrabar_guard.py").read_text(encoding="utf-8")
    tree=ast.parse(src)
    sql=[
        n.args[0].value for n in ast.walk(tree)
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
        and n.func.attr=="execute" and n.args
        and isinstance(n.args[0],ast.Constant)
        and isinstance(n.args[0].value,str)
        and "INSERT INTO aegis.shadow_trades" in n.args[0].value]
    assert len(sql)==1
    assert sql[0].count("%s")==19
    assert "ON CONFLICT(position_id) DO NOTHING RETURNING trade_id" in sql[0]
