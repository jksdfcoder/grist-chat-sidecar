from app.azure_csv import MemoryAzureCsv
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient

LIVE = "email,level,code\na@hku.hk,all,x\n"


def _client(email="boss@hku.hk"):
    s = Settings.model_validate(
        {
            "secret_key": "k" * 32,
            "e2e": True,
            "require_roles": True,
            "maintainers": ["keeper@hku.hk"],
            "managers": ["boss@hku.hk"],
            "allowed_email_domains": ["hku.hk"],
            "openrouter_api_key": "sk-test",
            "sqlite_path": ":memory:",
        }
    )
    app = create_app(s)
    mem = MemoryAzureCsv(LIVE, etag="1")
    app.state.azure_factory = lambda account, container, key, path: mem
    c = TestClient(app)
    c.post("/api/e2e/session", json={"email": email})
    return c, mem


def _conn():
    return {
        "dest": "azure",
        "account": "acct1",
        "container": "cont1",
        "path": "powerbi/users.csv",
        "account_key": "secret-key",
    }


def test_maintainer_commit_403():
    c, _ = _client("keeper@hku.hk")
    r = c.post("/api/upload/commit", json={**_conn(), "confirm": True, "columns": ["email"], "rows": []})
    assert r.status_code == 403


def test_templates_omit_key():
    c, _ = _client()
    r = c.post("/api/upload/templates", json={**_conn(), "name": "pbi"})
    assert r.status_code == 200
    listed = c.get("/api/upload/templates").json()["templates"]
    assert listed[0]["name"] == "pbi"
    blob = str(listed)
    assert "secret-key" not in blob
    assert "account_key" not in blob


def test_templates_rename_and_delete():
    c, _ = _client()
    tid = c.post("/api/upload/templates", json={**_conn(), "name": "pbi"}).json()["id"]
    assert c.patch(f"/api/upload/templates/{tid}", json={"name": ""}).status_code == 400
    assert c.patch(f"/api/upload/templates/{tid}", json={"name": "生产"}).status_code == 200
    listed = c.get("/api/upload/templates").json()["templates"]
    assert listed[0]["name"] == "生产"
    assert "secret-key" not in str(listed)
    assert c.delete(f"/api/upload/templates/{tid}").status_code == 200
    assert c.get("/api/upload/templates").json()["templates"] == []
    assert c.delete("/api/upload/templates/999").status_code == 404


def test_snapshot_upload_and_rollback():
    c, mem = _client()
    c.post("/api/upload/templates", json={**_conn(), "name": "pbi"})
    r = c.post(
        "/api/upload/commit",
        json={
            **_conn(),
            "confirm": True,
            "columns": ["email", "level"],
            "key_grist": "email",
            "key_csv": "email",
            "rows": [{"email": "a@hku.hk", "level": "faculty"}],
        },
    )
    assert r.status_code == 200, r.text
    body, _ = mem.read()
    assert "faculty" in body
    hist = c.get("/api/upload/history").json()["history"]
    assert hist[0]["kind"] == "upload"
    assert "secret-key" not in str(hist)
    hid = hist[0]["id"]
    rb = c.post(f"/api/upload/history/{hid}/rollback", json={"confirm": True})
    assert rb.status_code == 200, rb.text
    body, _ = mem.read()
    assert "all" in body
    kinds = [h["kind"] for h in c.get("/api/upload/history").json()["history"]]
    assert "rollback" in kinds


def test_commit_requires_confirm():
    c, mem = _client()
    r = c.post(
        "/api/upload/commit",
        json={**_conn(), "columns": ["email"], "key_grist": "email", "key_csv": "email", "rows": [{"email": "a@hku.hk"}]},
    )
    assert r.status_code == 400
    assert mem.read()[0] == LIVE


def test_request_then_commit_same_app():
    s = Settings.model_validate(
        {
            "secret_key": "k" * 32,
            "e2e": True,
            "require_roles": True,
            "maintainers": ["keeper@hku.hk"],
            "managers": ["boss@hku.hk"],
            "allowed_email_domains": ["hku.hk"],
            "openrouter_api_key": "sk-test",
            "sqlite_path": ":memory:",
        }
    )
    app = create_app(s)
    mem = MemoryAzureCsv(LIVE, etag="1")
    app.state.azure_factory = lambda account, container, key, path: mem
    c = TestClient(app)
    c.post("/api/e2e/session", json={"email": "keeper@hku.hk"})
    rid = c.post(
        "/api/upload/request",
        json={
            **_conn(),
            "columns": ["email", "level"],
            "key_grist": "email",
            "key_csv": "email",
            "rows": [{"email": "a@hku.hk", "level": "dept"}],
        },
    ).json()["id"]
    c.post("/api/e2e/session", json={"email": "boss@hku.hk"})
    r = c.post("/api/upload/commit", json={"confirm": True, "request_id": rid})
    assert r.status_code == 200, r.text
    assert "dept" in mem.read()[0]


def test_models_includes_role():
    c, _ = _client("keeper@hku.hk")
    body = c.get("/api/models").json()
    assert body["role"] == "maintainer"
    assert "openai" in body
    assert "openai_host" in body
    c, _ = _client()
    assert c.get("/api/models").json()["role"] == "manager"


def test_commit_maps_email_case():
    c, mem = _client()
    r = c.post(
        "/api/upload/commit",
        json={
            **_conn(),
            "confirm": True,
            "columns": ["Email", "level"],
            "key_grist": "Email",
            "key_csv": "Email",
            "rows": [{"Email": "a@hku.hk", "level": "faculty"}],
        },
    )
    assert r.status_code == 200, r.text
    body = mem.read()[0]
    assert "faculty" in body
    assert body.count("a@hku.hk") == 1


def test_db_dest_rejected():
    c, _ = _client()
    r = c.post("/api/upload/connect", json={**_conn(), "dest": "db"})
    assert r.status_code == 400


def test_connect_surfaces_error_type():
    c, _ = _client()

    class Boom:
        def read(self):
            raise ModuleNotFoundError("azure")

    c.app.state.azure_factory = lambda *a, **k: Boom()
    r = c.post("/api/upload/connect", json=_conn())
    assert r.status_code == 502
    assert r.json()["detail"] == "azure connect failed: ModuleNotFoundError"
