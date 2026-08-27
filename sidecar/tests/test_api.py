from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings

def _app(**over):
    s = Settings.model_validate({
        "secret_key": "k" * 32,
        "e2e": True,
        "require_roles": True,
        "maintainers": ["keeper@hku.hk"],
        "managers": ["boss@hku.hk"],
        "allowed_email_domains": ["hku.hk"],
        "openrouter_api_key": "sk-test",
        "sqlite_path": ":memory:",
        **over,
    })
    return TestClient(create_app(s))

def test_guest_sets_session():
    c = _app(e2e=False, require_roles=False, managers=[], maintainers=[], allowed_email_domains=[])
    r = c.get("/api/auth/guest", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/"
    assert c.get("/auth/verify").status_code == 200


def test_guest_cannot_commit():
    c = _app(e2e=False, require_roles=False, managers=[], maintainers=[], allowed_email_domains=[])
    c.get("/api/auth/guest", follow_redirects=False)
    r = c.post("/api/submit/commit", json={"rejected_keys": []})
    assert r.status_code == 403


def test_e2e_session_sets_max_age():
    c = _app()
    r = c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    assert r.status_code == 200
    assert "Max-Age=" in (r.headers.get("set-cookie") or "")


def test_e2e_session_404_when_disabled():
    c = _app(e2e=False)
    assert c.post("/api/e2e/session", json={"email": "boss@hku.hk"}).status_code == 404
    assert c.get("/api/e2e/login").status_code == 404

def test_maintainer_commit_403():
    c = _app()
    c.post("/api/e2e/session", json={"email": "keeper@hku.hk"})
    r = c.post("/api/submit/commit", json={"rejected_keys": []})
    assert r.status_code == 403

def test_submit_html_hides_commit_for_maintainer():
    c = _app()
    c.post("/api/e2e/session", json={"email": "keeper@hku.hk"})
    html = c.get("/submit").text
    assert 'data-testid="commit"' not in html
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    html = c.get("/submit").text
    assert 'data-testid="commit"' in html

def test_stale_role_revokes_verify():
    c = _app()
    assert c.post("/api/e2e/session", json={"email": "boss@hku.hk"}).status_code == 200
    assert c.get("/auth/verify").status_code == 200
    c.app.state.settings.managers = []
    c.app.state.settings.maintainers = []
    assert c.get("/auth/verify").status_code == 401

def test_allowlist_drop_revokes_verify():
    c = _app()
    assert c.post("/api/e2e/session", json={"email": "boss@hku.hk"}).status_code == 200
    c.app.state.settings.allowed_emails = ["other@hku.hk"]
    c.app.state.settings.allowed_email_domains = []
    c.app.state.settings.allowed_provider_ids = []
    assert c.get("/auth/verify").status_code == 401

def test_write_without_email_then_prepare_is_empty():
    c = _app()
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    c.post("/api/grist/write", json={"rows": [{"ok": 1}], "key": "Email"})
    assert c.post("/api/submit/prepare", json={}).json()["hunks"] == []

def test_write_then_prepare_shows_append():
    c = _app()
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    c.post("/api/grist/write", json={"rows": [{"Email": "new@hku.hk", "Name": "New"}], "key": "Email"})
    hunks = c.post("/api/submit/prepare", json={}).json()["hunks"]
    assert hunks and hunks[0]["kind"] == "append"
    assert hunks[0]["key"] == "new@hku.hk"
    insecure = _app(cookie_secure=False).post("/api/e2e/session", json={"email": "boss@hku.hk"})
    assert "secure" not in insecure.headers["set-cookie"].lower()
    secure = _app(cookie_secure=True).post("/api/e2e/session", json={"email": "boss@hku.hk"})
    assert "secure" in secure.headers["set-cookie"].lower()


def test_save_sql_note_and_select_only():
    c = _app()
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    assert c.post("/api/sql", json={"sql": "SELECT 1", "db": "hub"}).status_code == 400
    assert c.post("/api/sql", json={"sql": "INSERT INTO t VALUES (1)", "note": "no", "db": "hub"}).status_code == 400
    r = c.post("/api/sql", json={"sql": "SELECT 1 AS ok", "note": "ping", "db": "hub"})
    assert r.status_code == 200
    items = c.get("/api/sql").json()
    assert items[0]["note"] == "ping"
    assert items[0]["db"] == "hub"
    assert items[0]["author"] == "boss@hku.hk"
    assert "LIMIT" in items[0]["sql"].upper()
    sid = items[0]["id"]
    assert c.patch(f"/api/sql/{sid}", json={"note": "pong"}).status_code == 200
    assert c.get("/api/sql").json()[0]["note"] == "pong"
    assert c.delete(f"/api/sql/{sid}").status_code == 200
    assert c.get("/api/sql").json() == []
    assert c.delete("/api/sql/999").status_code == 404


def test_models_and_rejects_unknown():
    c = _app(openrouter_stub="ask")
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    ids = [m["id"] for m in c.get("/api/models").json()["models"]]
    assert "openrouter/free" in ids
    assert "~deepseek/deepseek-v4-flash-latest" in ids
    assert c.post(
        "/api/chat/turn", json={"messages": [], "model": "openai/gpt-4", "effort": "high"}
    ).status_code == 400
    assert c.post(
        "/api/chat/turn", json={"messages": [{"role": "user", "content": "hi"}], "model": "openrouter/free"}
    ).status_code == 200
    prev = c.post(
        "/api/chat/turn",
        json={
            "messages": [{"role": "user", "content": "找人"}],
            "tool_results": [{"id": "stub-ask", "output": "staff"}],
        },
    ).json()["previews"][0]
    assert prev["note"].startswith("Input:")
    assert "Email" in prev["note"]
    assert "找人" not in prev["note"]
    assert "new@hku.hk" not in prev["note"]


def test_chat_turn_ndjson_stub():
    import json

    c = _app(openrouter_stub="ask")
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    r = c.post(
        "/api/chat/turn",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Accept": "application/x-ndjson"},
    )
    assert r.status_code == 200
    assert "ndjson" in r.headers["content-type"]
    lines = [json.loads(x) for x in r.text.strip().splitlines() if x.strip()]
    assert lines[-1]["type"] == "done"
    assert lines[-1]["tool_calls"][0]["name"] == "ask_question"


def test_sql_preview_exec_select_only():
    c = _app()
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    assert c.post("/api/sql/preview", json={"sql": "INSERT INTO t VALUES (1)", "db": "hub"}).status_code == 400
    r = c.post("/api/sql/preview", json={"sql": "SELECT 1 AS ok", "db": "hub"})
    assert r.status_code == 200
    assert r.json()["rows"]
    assert c.post(
        "/api/sql/preview",
        json={"sql": "SELECT {{Email}} AS email", "db": "hub"},
    ).status_code == 400
    bound = c.post(
        "/api/sql/preview",
        json={
            "sql": "SELECT {{Email}} AS email",
            "db": "hub",
            "binds": {"Email": ["a@hku.hk"]},
        },
    )
    assert bound.status_code == 200
    assert bound.json()["rows"]
    rp = c.post(
        "/api/sql/preview",
        json={"sql": 'SELECT {{RP_no}} AS "RP_no"', "db": "hub", "binds": {"RP_no": ["rp00402"]}},
    )
    assert rp.status_code == 200
    assert "rp00402" in str(rp.json())


def test_chat_debug_has_no_cell_values():
    c = _app(openrouter_stub="ask")
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    c.post("/api/chat/turn", json={"messages": [{"role": "user", "content": "hi"}], "sheet_columns": ["RP_no"]})
    c.post(
        "/api/chat/debug",
        json={"event": "write", "status": "SQL has no {{column}}", "cols": ["RP_no"], "ph": [], "sql": "SELECT 'rp00020'"},
    )
    events = c.get("/api/chat/debug").json()
    blob = str(events)
    assert events[0]["event"] == "write"
    assert any(e.get("event") == "turn" and e.get("cols") == ["RP_no"] for e in events)
    assert "rp00020" not in blob
    assert "SELECT" not in blob
    assert "hi" not in blob


def test_chat_html_busts_static_cache():
    c = _app()
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    html = c.get("/chat").text
    assert "/static/chat/app.js?v=" in html
    assert "/static/chat/app.css?v=" in html


def test_openai_connect_saves_and_lists(monkeypatch):
    from app import chat

    chat._CACHE = (0.0, [])

    def fake_get(url, headers=None, timeout=None):
        class R:
            def raise_for_status(self):
                return None

            def json(self):
                if "25890" in url:
                    return {"data": [{"id": "qwen3.8-27b"}]}
                return {"data": []}

        return R()

    monkeypatch.setattr(chat.httpx, "get", fake_get)
    c = _app()
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    assert c.post("/api/models/openai", json={"base_url": ""}).status_code == 400
    r = c.post(
        "/api/models/openai",
        json={"base_url": "http://127.0.0.1:25890/v1", "api_key": "sk-test"},
    )
    assert r.status_code == 200, r.text
    assert "sk-test" not in r.text
    body = r.json()
    assert body["openai"] is True
    assert body["openai_host"] == "127.0.0.1:25890"
    assert any(m["id"] == "qwen3.8-27b" for m in body["models"])
    listed = c.get("/api/models").json()
    assert listed["openai_base_url"].endswith("25890/v1")
    assert "api_key" not in listed
    assert any(m["id"] == "qwen3.8-27b" for m in listed["models"])


def test_openai_connect_fail_does_not_save(monkeypatch):
    import httpx
    from app import chat

    chat._CACHE = (0.0, [])

    def fake_get(url, headers=None, timeout=None):
        if "25890" in url:
            raise httpx.ConnectError("down")

        class R:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": []}

        return R()

    monkeypatch.setattr(chat.httpx, "get", fake_get)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = _app(openai_base_url="", openai_api_key="")
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    r = c.post(
        "/api/models/openai",
        json={"base_url": "http://127.0.0.1:25890/v1", "api_key": "sk-test"},
    )
    assert r.status_code == 502
    assert c.get("/api/models").json()["openai"] is False
