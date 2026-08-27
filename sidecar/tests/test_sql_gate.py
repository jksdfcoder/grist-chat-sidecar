from app.sql_gate import gate_select

def test_rejects_insert():
    try:
        gate_select("INSERT INTO t VALUES (1)")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

def test_rejects_second_statement():
    try:
        gate_select("SELECT 1; DROP TABLE t")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

def test_adds_limit():
    out = gate_select("SELECT * FROM t")
    assert "LIMIT" in out.upper()
    assert "20" in out

def test_caps_large_limit():
    out = gate_select("SELECT * FROM t LIMIT 100")
    assert "100" not in out.split("LIMIT", 1)[-1] or "LIMIT 20" in out.upper().replace("\n", " ")

def test_rejects_select_into():
    try:
        gate_select("SELECT * INTO t FROM s")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

def test_rejects_insert_in_with():
    try:
        gate_select("WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_bind_placeholders():
    from app.sql_gate import bind_placeholders, sql_for_gate

    assert "NULL" in sql_for_gate("SELECT * FROM t WHERE email IN ({{Email}})")
    out = bind_placeholders(
        "SELECT * FROM t WHERE email IN ({{Email}})",
        {"Email": ["a@hku.hk", "o'reilly@hku.hk"]},
    )
    assert "'a@hku.hk'" in out
    assert "'o''reilly@hku.hk'" in out
    assert "rp00402" in bind_placeholders("SELECT {{RP_no}}", {"RP_no": ["rp00402"]})
    eq = bind_placeholders(
        "SELECT fullname FROM t WHERE crisid = '{{RP_no}}'",
        {"RP_no": ["rp00401", "rp00020"]},
    )
    assert "IN (" in eq
    assert "rp00401" in eq
    assert "= '" not in eq.split("crisid", 1)[-1]
    one = bind_placeholders("WHERE crisid = '{{RP_no}}'", {"RP_no": ["rp00402"]})
    assert one == "WHERE crisid = 'rp00402'"
    quoted_in = bind_placeholders("WHERE id IN ('{{RP_no}}')", {"RP_no": ["rp00402", "rp00020"]})
    assert quoted_in == "WHERE id IN ('rp00402', 'rp00020')"
    try:
        bind_placeholders("SELECT {{Email}}", {})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_select_lookup_cols():
    from app.sql_gate import bind_placeholders, select_lookup_cols

    sql = 'SELECT fullname AS "Name", email AS "Email" FROM t WHERE crisid = \'{{RP_no}}\''
    out = select_lookup_cols(sql)
    assert 'crisid AS "RP_no"' in out
    assert out.startswith('SELECT crisid AS "RP_no", ')
    same = 'SELECT crisid AS "RP_no", fullname AS "Name" FROM t WHERE crisid IN ({{RP_no}})'
    assert select_lookup_cols(same) == same
    bound = bind_placeholders(out, {"RP_no": ["rp1", "rp2"]})
    assert 'crisid AS "RP_no"' in bound
    assert "IN (" in bound


def test_pg_error_uses_primary():
    from app.chat import pg_error

    class Diag:
        message_primary = "operator does not exist: integer = character varying"

    class Boom(Exception):
        diag = Diag()

    assert str(pg_error(Boom("x"))) == "operator does not exist: integer = character varying"


def test_pg_error_timeout_is_dead_path():
    from app.chat import pg_error

    class Diag:
        message_primary = "canceling statement due to statement timeout"

    class Boom(Exception):
        diag = Diag()

    msg = str(pg_error(Boom("x"), 5000))
    assert msg.startswith("path blocked")
    assert "5000ms" in msg
    assert "Do not retry" in msg


def test_rejects_expensive_or_unsafe_sql():
    bad = [
        ("SELECT pg_sleep(1)", "pg_sleep"),
        ("SELECT set_config('statement_timeout','0',false)", "set_config"),
        ("SELECT * FROM t FOR UPDATE", "FOR UPDATE"),
        (
            "WITH RECURSIVE x AS (SELECT 1 AS n UNION ALL SELECT n+1 FROM x) SELECT * FROM x",
            "RECURSIVE",
        ),
        ("SELECT * FROM t OFFSET 1000", "OFFSET"),
        ("SELECT * FROM t WHERE x LIKE '%' || y", "full table scan"),
        ("SELECT * FROM cris.metadata", "path blocked"),
        ("SELECT * FROM pg_catalog.pg_authid", "catalog"),
        ("SELECT * FROM generate_series(1, 1000000)", "generate_series"),
    ]
    for sql, needle in bad:
        try:
            gate_select(sql)
            raise AssertionError(sql)
        except ValueError as e:
            assert needle.lower() in str(e).lower(), (sql, e)
    from app.sql_gate import sql_for_gate

    assert "LIMIT" in gate_select("SELECT 1 FROM cris.metadata WHERE id = 1").upper()
    assert "LIMIT" in gate_select(
        sql_for_gate(
            "SELECT v.crisid FROM cris.researcherpage_view v "
            "JOIN cris.metadata m ON m.id = v.id AND m.resourcetype = 'rp' "
            "WHERE v.crisid IN ({{RP_no}})"
        )
    ).upper()
