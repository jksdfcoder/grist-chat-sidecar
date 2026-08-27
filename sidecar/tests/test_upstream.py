from app.settings import Settings
from app.upstream import connect


def test_connect_sets_readonly_after_connect(monkeypatch):
    seen = {}
    sets = []

    class Cur:
        def execute(self, sql):
            sets.append(sql)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    class Conn:
        autocommit = False

        def cursor(self):
            return Cur()

        def close(self):
            return None

    def fake_connect(**kw):
        seen.update(kw)
        return Conn()

    monkeypatch.setattr("psycopg2.connect", fake_connect)
    s = Settings.model_validate({
        "upstream_db_host": "db.example",
        "upstream_hub_user": "hubu",
        "upstream_hub_password": "hubp",
        "upstream_dspace_user": "dspu",
        "upstream_dspace_password": "dspp",
    })
    conn = connect(s, "hub")
    assert seen["dbname"] == "hub"
    assert conn.autocommit is True
    assert "options" not in seen
    assert any("read_only" in sql for sql in sets)
    assert any("statement_timeout" in sql for sql in sets)
    assert any("5000" in sql for sql in sets)
    sets.clear()
    connect(s, "hub", statement_timeout_ms=30000)
    assert any("30000" in sql for sql in sets)
    connect(s, "dspace")
    assert seen["dbname"] == "dspace"
    assert seen["user"] == "dspu"


def test_canonical_env_names(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:25890/v1")
    monkeypatch.setenv("UPSTREAM_DB_HOST", "db.example")
    monkeypatch.setenv("SIH_AUTH_ALLOWED_EMAIL_DOMAINS", "example.com")
    s = Settings()
    assert s.openrouter_api_key == "or-key"
    assert s.openai_base_url == "http://127.0.0.1:25890/v1"
    assert s.upstream_db_host == "db.example"
    assert s.allowed_email_domains == ["example.com"]
