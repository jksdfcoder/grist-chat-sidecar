import hashlib
import json
import logging
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.azure_csv import AdlsAzureCsv, EtagMismatch, MemoryAzureCsv
from app import chat as chat_mod
from app.chat import (
    _get_models,
    catalog,
    cookbook_clause,
    exec_sql,
    make_client,
    note_from_sql,
    openai_models,
    resolve_effort,
    resolve_model,
    iter_turn,
    run_turn,
)
from app.sql_gate import gate_select, sql_for_gate
from app.grist import MemoryGrist
from app.hkul import is_hkul_access_allowed
from app.pending import ExpiredPending, PendingStore
from app.propose import ColumnMap, commit_pending, propose_csv
from app.roles import role_for
from app.session import _MAX_AGE, dump_session, load_session
from app.settings import Settings
from app.upload import check_dest, clean_rows, cols, connect, default_keys, key_for_path, proposed_csv, resolve_conn, snapshot_write

COOKIE = "sih_ver2"
ROOT = Path(__file__).resolve().parent.parent
AZURE_SEED = "Email,Name\nseed@hku.hk,Seed\n"
_COL = re.compile(r"^[A-Za-z_]\w{0,63}$")


def _names(xs) -> list[str]:
    out = []
    for x in xs or []:
        s = str(x)
        if _COL.match(s) and s not in out:
            out.append(s)
        if len(out) >= 40:
            break
    return out


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    if s.require_roles:
        s.validate_roles()
    app = FastAPI()
    app.state.settings = s
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    azure = MemoryAzureCsv(AZURE_SEED)
    grist = MemoryGrist()
    store = PendingStore(s.sqlite_path)
    saved = store.get_openai()
    if saved:
        s.openai_base_url = saved["base_url"]
        s.openai_api_key = saved["api_key"]
    # ponytail: tests swap azure_factory for MemoryAzureCsv
    app.state.azure_factory = lambda account, container, key, path: AdlsAzureCsv(account, container, key, path)
    # ponytail: last 40 events; gone on reload. grep docker logs for "sih "
    app.state.debug = deque(maxlen=40)

    def dbg(**kv):
        row = {"t": int(time.time())}
        for k, v in kv.items():
            if v in (None, "", [], ()):
                continue
            row[k] = v
        app.state.debug.appendleft(row)
        logging.getLogger("uvicorn.error").info(
            "sih " + " ".join(f"{k}={row[k]}" for k in row if k != "t")
        )

    def sess(request: Request):
        token = request.cookies.get(COOKIE)
        return load_session(token, s.secret_key) if token else None

    def live_user(request: Request):
        got = sess(request)
        if got is None or not got.get("email"):
            return None
        if s.require_roles:
            if not is_hkul_access_allowed(
                email=got["email"],
                provider_id=got.get("providerId") or "",
                allowed_emails=s.allowed_emails,
                allowed_email_domains=s.allowed_email_domains,
                allowed_provider_ids=s.allowed_provider_ids,
            ):
                return None
            role = role_for(got["email"], s.maintainers, s.managers)
            if role is None:
                return None
        else:
            role = role_for(got["email"], s.maintainers, s.managers) or "maintainer"
        return {"email": got["email"], "providerId": got.get("providerId") or "", "name": got.get("name") or "", "role": role}

    def require(request: Request, *roles):
        got = live_user(request)
        if got is None:
            raise HTTPException(401)
        if roles and got["role"] not in roles:
            raise HTTPException(403)
        return got

    def set_session(resp, payload):
        resp.set_cookie(
            COOKIE,
            dump_session(payload, s.secret_key),
            httponly=True,
            samesite="lax",
            secure=s.cookie_secure,
            max_age=_MAX_AGE,
        )
        return resp

    @app.get("/api/auth/guest")
    def guest_login():
        resp = RedirectResponse("/", status_code=302)
        return set_session(resp, {"email": "guest@local", "providerId": "guest", "name": "Guest"})

    @app.get("/auth/verify")
    def verify(request: Request):
        got = live_user(request)
        if not got:
            raise HTTPException(401)
        return Response(status_code=200, headers={"X-Forwarded-User": got["email"]})

    def _e2e_cookie(email: str, resp):
        if not s.e2e:
            raise HTTPException(404)
        if role_for(email, s.maintainers, s.managers) is None:
            raise HTTPException(403)
        return set_session(resp, {"email": email, "providerId": "e2e", "name": email})

    @app.post("/api/e2e/session")
    def e2e_session(body: dict):
        return _e2e_cookie(body.get("email") or "", Response(status_code=200))

    @app.get("/api/e2e/login")
    def e2e_login(email: str = "boss@hku.hk"):
        return _e2e_cookie(email, RedirectResponse("/", status_code=302))

    @app.post("/api/sql/preview")
    def sql_preview(request: Request, body: dict):
        require(request, "manager", "maintainer")
        db = body.get("db") or "hub"
        if db not in ("hub", "dspace"):
            raise HTTPException(400, "bad db")
        ph = re.findall(r"\{\{(\w+)\}\}", body.get("sql") or "")
        binds = _names((body.get("binds") or {}).keys()) if isinstance(body.get("binds"), dict) else []
        try:
            out = exec_sql(body.get("sql") or "", s, db, binds=body.get("binds"))
            dbg(event="preview", db=db, ph=ph, binds=binds, n=len(out.get("rows") or []), sql=(body.get("sql") or "")[:160])
            return out
        except ValueError as e:
            dbg(event="preview", db=db, ph=ph, binds=binds, err=str(e)[:180])
            raise HTTPException(400, str(e))

    @app.get("/api/sql")
    def sql_list(request: Request):
        require(request, "manager", "maintainer")
        return store.list_sql()

    @app.post("/api/sql")
    def sql_save(request: Request, body: dict):
        got = require(request, "manager", "maintainer")
        note = (body.get("note") or "").strip()
        if not note:
            raise HTTPException(400, "note required")
        db = body.get("db") or "hub"
        if db not in ("hub", "dspace"):
            raise HTTPException(400, "bad db")
        try:
            raw_sql = body.get("sql") or ""
            gate_select(sql_for_gate(raw_sql))
            sql = raw_sql if "{{" in raw_sql else gate_select(raw_sql)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": store.save_sql(sql=sql, note=note, db=db, author=got["email"])}

    @app.delete("/api/sql/{sql_id}")
    def sql_delete(request: Request, sql_id: int):
        require(request, "manager", "maintainer")
        if not store.delete_sql(sql_id):
            raise HTTPException(404, "not found")
        return {"ok": True}

    @app.patch("/api/sql/{sql_id}")
    def sql_rename(request: Request, sql_id: int, body: dict):
        require(request, "manager", "maintainer")
        note = (body.get("note") or "").strip()[:200]
        if not note:
            raise HTTPException(400, "note required")
        if not store.rename_sql(sql_id, note):
            raise HTTPException(404, "not found")
        return {"ok": True}

    @app.get("/api/models")
    def models(request: Request):
        got = require(request, "manager", "maintainer")
        items = catalog(s)
        default = s.openrouter_model
        if default not in {m["id"] for m in items}:
            default = items[0]["id"] if items else ""
        return {
            "models": items,
            "default": default,
            "role": got["role"],
            "openai": bool((s.openai_base_url or "").strip()),
            "openai_host": urlparse((s.openai_base_url or "").strip()).netloc,
            "openai_base_url": (s.openai_base_url or "").strip(),
        }

    @app.post("/api/models/openai")
    def openai_connect(request: Request, body: dict):
        require(request, "manager", "maintainer")
        url = (body.get("base_url") or "").strip().rstrip("/")
        key = (body.get("api_key") or "").strip()
        if not url:
            raise HTTPException(400, "base_url required")
        if not key:
            prev = store.get_openai() or {}
            key = (prev.get("api_key") or s.openai_api_key or "").strip()
        try:
            openai_models(_get_models(url, key))
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            raise HTTPException(502, f"openai connect failed: {type(e).__name__}")
        store.set_openai(url, key)
        s.openai_base_url = url
        s.openai_api_key = key
        chat_mod._CACHE = (0.0, [])
        return {
            "ok": True,
            "models": catalog(s),
            "openai": True,
            "openai_host": urlparse(url).netloc,
            "openai_base_url": url,
        }

    def _decorate_turn(result, body):
        for preview in result.get("previews") or []:
            preview["note"] = note_from_sql(preview.get("sql") or "")
        sql = ((result.get("previews") or [{}])[0] or {}).get("sql") or ""
        tools = [t.get("name") for t in result.get("tool_calls") or []]
        if not tools:
            tools = ["preview"] if result.get("previews") else ["text"]
        dbg(
            event="turn",
            cols=_names(body.get("sheet_columns")),
            tools=tools,
            ph=re.findall(r"\{\{(\w+)\}\}", sql),
            err=None if result.get("previews") or tools[:1] == ["ask_question"] else str(result.get("text") or "")[:180],
        )
        return result

    @app.post("/api/chat/turn")
    def chat_turn(request: Request, body: dict):
        require(request, "manager", "maintainer")
        try:
            model = resolve_model(body.get("model"), s)
            effort = resolve_effort(body.get("effort"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        kw = dict(
            client=None if s.openrouter_stub else make_client(s, model),
            settings=s,
            messages=body.get("messages") or [],
            tool_results=body.get("tool_results"),
            model=model,
            effort=effort,
            sheet_columns=body.get("sheet_columns"),
            cookbook=cookbook_clause(
                store.list_sql(),
                next((m.get("content") or "" for m in reversed(body.get("messages") or []) if m.get("role") == "user"), ""),
            ),
        )
        keys = ("text", "reasoning", "tool_calls", "previews", "tools")
        if "ndjson" not in (request.headers.get("accept") or ""):
            return _decorate_turn(run_turn(**kw), body)

        def gen():
            for ev in iter_turn(**kw):
                if ev.get("type") == "done":
                    done = _decorate_turn({k: ev.get(k) for k in keys}, body)
                    yield json.dumps({"type": "done", **done}, ensure_ascii=False) + "\n"
                else:
                    yield json.dumps(ev, ensure_ascii=False) + "\n"

        return StreamingResponse(
            gen(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/chat/debug")
    def chat_debug(request: Request):
        require(request, "manager", "maintainer")
        return list(app.state.debug)

    @app.post("/api/chat/debug")
    def chat_debug_post(request: Request, body: dict):
        require(request, "manager", "maintainer")
        dbg(
            event=re.sub(r"[^a-z0-9_-]", "", str(body.get("event") or "ui").lower())[:32] or "ui",
            status=str(body.get("status") or "")[:180],
            cols=_names(body.get("cols")),
            ph=_names(body.get("ph")),
            n=body.get("n") if isinstance(body.get("n"), int) and 0 <= body["n"] < 10_000 else None,
        )
        return {"ok": True}

    @app.post("/api/grist/write")
    def grist_write(request: Request, body: dict):
        require(request, "manager", "maintainer")
        grist.upsert(body.get("rows") or [], body.get("key") or "Email", body.get("column_map") or {})
        return {"ok": True}

    @app.post("/api/submit/prepare")
    async def submit_prepare(request: Request):
        got = require(request, "manager", "maintainer")
        raw = await request.body()
        body = json.loads(raw) if raw else {}
        key = body.get("key") or "Email"
        cmap = body.get("column_map") or {"Email": "Email", "Name": "Name"}
        mapping = ColumnMap(
            key_grist=key,
            key_csv=body.get("key_csv") or key,
            columns=list(cmap.items()),
        )
        live, etag = azure.read()
        result = propose_csv(live, grist.list_rows(), mapping)
        store.save(
            {
                "etag": etag,
                "map": {
                    "key_grist": mapping.key_grist,
                    "key_csv": mapping.key_csv,
                    "columns": [list(p) for p in mapping.columns],
                },
                "proposed_csv": result.csv_text,
                "sha256": hashlib.sha256(result.csv_text.encode()).hexdigest(),
                "author_email": got["email"],
                "expires_at": time.time() + 30 * 60,
                "hunks": result.hunks,
                "live_csv": live,
                "warnings": result.warnings,
            }
        )
        return {"hunks": result.hunks, "warnings": result.warnings}

    @app.get("/api/submit/pending")
    def submit_pending(request: Request):
        require(request, "manager", "maintainer")
        return store.get() or {}

    @app.post("/api/submit/commit")
    async def submit_commit(request: Request):
        got = require(request, "manager")
        raw = await request.body()
        body = json.loads(raw) if raw else {}
        try:
            etag = commit_pending(
                store, azure, actor_email=got["email"], rejected_keys=body.get("rejected_keys") or []
            )
        except EtagMismatch:
            raise HTTPException(409)
        except ExpiredPending:
            raise HTTPException(409)
        return {"ok": True, "etag": etag}

    def _azure_conn(body: dict):
        dest = check_dest(body.get("dest") or "azure")
        account, container, key, path = resolve_conn(body, store)
        client = app.state.azure_factory(account, container, key, path)
        return dest, account, container, key, path, client

    @app.get("/api/upload/templates")
    def upload_templates(request: Request):
        require(request, "manager", "maintainer")
        return {"templates": store.list_templates()}

    @app.post("/api/upload/templates")
    def upload_templates_save(request: Request, body: dict):
        got = require(request, "manager", "maintainer")
        try:
            account, container, key, path = resolve_conn(body, store)
            name = (body.get("name") or f"{account}/{path}").strip()[:80]
            tid = store.save_template(
                name=name, account=account, container=container, path=path, account_key=key, author=got["email"]
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": tid}

    @app.patch("/api/upload/templates/{tid}")
    def upload_templates_rename(request: Request, tid: int, body: dict):
        require(request, "manager", "maintainer")
        name = (body.get("name") or "").strip()[:80]
        if not name:
            raise HTTPException(400, "name required")
        if not store.rename_template(tid, name):
            raise HTTPException(404, "not found")
        return {"ok": True}

    @app.delete("/api/upload/templates/{tid}")
    def upload_templates_delete(request: Request, tid: int):
        require(request, "manager", "maintainer")
        if not store.delete_template(tid):
            raise HTTPException(404, "not found")
        return {"ok": True}

    @app.post("/api/upload/connect")
    def upload_connect(request: Request, body: dict):
        require(request, "manager", "maintainer")
        try:
            dest, account, container, key, path, client = _azure_conn(body)
            out = connect(client)
            out["dest"] = dest
            out["account"] = account
            out["container"] = container
            out["path"] = path
            selected = cols(body.get("columns"))
            out["key_grist"], out["key_csv"] = default_keys(selected or out["columns"], out["columns"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(502, f"azure connect failed: {type(e).__name__}")
        return out

    @app.get("/api/upload/requests")
    def upload_requests(request: Request):
        got = require(request, "manager", "maintainer")
        if got["role"] == "manager":
            return {"requests": store.list_upload_requests()}
        return {"requests": store.list_upload_requests(author=got["email"])}

    @app.post("/api/upload/request")
    def upload_request(request: Request, body: dict):
        got = require(request, "manager", "maintainer")
        try:
            dest, account, container, key, path, _client = _azure_conn(body)
            selected = cols(body.get("columns"))
            if not selected:
                raise ValueError("columns required")
            key_grist = (body.get("key_grist") or selected[0]).strip()
            key_csv = (body.get("key_csv") or key_grist).strip()
            if key_grist not in selected:
                raise ValueError("key column not selected")
            rows = clean_rows(body.get("rows"), selected)
            rid = store.add_upload_request(
                {
                    "author": got["email"],
                    "dest": dest,
                    "template_id": body.get("template_id"),
                    "account": account,
                    "container": container,
                    "path": path,
                    "account_key": key,
                    "columns": selected,
                    "key_grist": key_grist,
                    "key_csv": key_csv,
                    "rows": rows,
                    "note": (body.get("note") or "")[:200],
                }
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": rid}

    @app.post("/api/upload/commit")
    def upload_commit(request: Request, body: dict):
        got = require(request, "manager")
        if body.get("confirm") is not True:
            raise HTTPException(400, "confirm required")
        try:
            req = store.get_upload_request(int(body["request_id"])) if body.get("request_id") else None
            if body.get("request_id") and (not req or req["status"] != "pending"):
                raise HTTPException(404, "no request")
            src = req if req else body
            conn_body = {
                "dest": src.get("dest") or "azure",
                "template_id": src.get("template_id") if not (src.get("account") and src.get("account_key")) else None,
                "account": src.get("account"),
                "container": src.get("container"),
                "path": src.get("path"),
                "account_key": src.get("account_key"),
            }
            dest, account, container, key, path, client = _azure_conn(conn_body)
            selected = cols(src.get("columns"))
            if not selected:
                raise ValueError("columns required")
            key_grist = (src.get("key_grist") or selected[0]).strip()
            key_csv = (src.get("key_csv") or key_grist).strip()
            rows = clean_rows(src.get("rows") if req else body.get("rows"), selected)
            live, _etag = client.read()
            new_body = proposed_csv(live, rows, selected, key_grist, key_csv)
            new_etag, hid = snapshot_write(
                store, client, author=got["email"], kind="upload", dest=dest,
                account=account, container=container, path=path, new_body=new_body,
                columns=selected, note=(body.get("note") or "")[:200],
            )
            if req:
                store.mark_request(req["id"], "done")
            tname = (body.get("template_name") or "").strip()[:80]
            if tname and key:
                store.save_template(
                    name=tname, account=account, container=container, path=path, account_key=key, author=got["email"]
                )
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(400, str(e))
        except EtagMismatch:
            raise HTTPException(409, "etag mismatch")
        except Exception:
            raise HTTPException(502, "azure upload failed")
        return {"ok": True, "etag": new_etag, "history_id": hid}

    @app.get("/api/upload/history")
    def upload_history(request: Request):
        require(request, "manager")
        return {"history": store.list_upload_hist()}

    @app.post("/api/upload/history/{hid}/rollback")
    def upload_rollback(request: Request, hid: int, body: dict):
        got = require(request, "manager")
        if body.get("confirm") is not True:
            raise HTTPException(400, "confirm required")
        rec = store.get_upload_hist(hid)
        if not rec:
            raise HTTPException(404, "not found")
        try:
            dest = check_dest(rec["dest"])
            key = key_for_path(store, rec["account"], rec["container"], rec["path"], body)
            client = app.state.azure_factory(rec["account"], rec["container"], key, rec["path"])
            new_etag, new_hid = snapshot_write(
                store, client, author=got["email"], kind="rollback", dest=dest,
                account=rec["account"], container=rec["container"], path=rec["path"], new_body=rec["body"],
                columns=rec["columns"], note=f"rollback {hid}",
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except EtagMismatch:
            raise HTTPException(409, "etag mismatch")
        except Exception:
            raise HTTPException(502, "azure rollback failed")
        return {"ok": True, "etag": new_etag, "history_id": new_hid}

    @app.get("/chat")
    def chat_page(request: Request):
        got = live_user(request)
        if not got:
            return RedirectResponse("/api/auth/guest", status_code=302)
        js = ROOT / "static/chat/app.js"
        return templates.TemplateResponse(
            request,
            "chat.html",
            {
                "role": got["role"],
                "chat_v": int(js.stat().st_mtime) if js.is_file() else 0,
            },
        )

    @app.get("/submit")
    def submit_page(request: Request):
        got = live_user(request)
        if not got:
            return RedirectResponse("/api/auth/guest", status_code=302)
        return templates.TemplateResponse(request, "submit.html", {"role": got["role"]})

    return app


app = create_app()
