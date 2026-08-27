import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
from openai import OpenAI

from app.sql_gate import bind_placeholders, gate_select, select_lookup_cols, sql_for_gate
from app.upstream import connect as pg_connect

SYSTEM = Path(__file__).with_name("upstream_prompt.md").read_text()  # reload this module after prompt edits
LOCAL_SYSTEM = Path(__file__).with_name("upstream_local_prompt.md").read_text()
_COL_ID = re.compile(r"^[A-Za-z_]\w{0,63}$")
_SKIP_COLS = {"id", "manualSort"}
PAID_MODEL = "~deepseek/deepseek-v4-flash-latest"
PAID_NAME = "DeepSeek V4 Flash Latest"
EFFORTS = ("none", "low", "medium", "high", "xhigh")
_STUB_MODELS = [
    {"id": "openrouter/free", "name": "Free Models Router", "free": True},
    {"id": PAID_MODEL, "name": PAID_NAME, "free": False},
]
# ponytail: 1h memory cache; restart the process if the catalog is stale
_CACHE: tuple[float, list[dict]] = (0.0, [])

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_question",
            "description": "Ask which sheet column to use. options must be sheet column names. Never ask for RP ids, emails, or other cell values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "kind": {"type": "string", "enum": ["text", "single", "multi"]},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question", "kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": "List upstream tables.",
            "parameters": {"type": "object", "properties": {"db": {"type": "string", "enum": ["hub", "dspace"]}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_table",
            "description": "Describe one table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "db": {"type": "string", "enum": ["hub", "dspace"]},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_sql",
            "description": "Propose a SELECT. Server EXPLAINs it then (local) samples. On {error} starting with path blocked, that SQL is dead: different table or an equality/prefix filter, never retry it. Other {error}: fix and call again. The user only sees the last passing SQL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "db": {"type": "string", "enum": ["hub", "dspace"]},
                },
                "required": ["sql"],
            },
        },
    },
]


def _is_free(model: dict) -> bool:
    pricing = model.get("pricing") or {}
    try:
        return float(pricing.get("prompt") or 0) == 0 and float(pricing.get("completion") or 0) == 0
    except (TypeError, ValueError):
        return False


def reach_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    # ponytail: compose sidecar's 127.0.0.1 is the container; extra_hosts maps host.docker.internal
    if u and Path("/.dockerenv").exists():
        u = u.replace("://127.0.0.1", "://host.docker.internal").replace("://localhost", "://host.docker.internal")
    return u


def openai_models(raw: list) -> list[dict]:
    out = []
    for model in raw:
        mid = str(model.get("id") or "").strip()
        if mid:
            out.append({"id": mid, "name": str(model.get("name") or mid), "free": True, "via": "openai"})
    return out


def pick_models(raw: list) -> list[dict]:
    out = []
    for model in raw:
        params = model.get("supported_parameters") or []
        if "tools" not in params or not _is_free(model):
            continue
        mid = model.get("id") or ""
        if not mid or mid == PAID_MODEL:
            continue
        out.append({"id": mid, "name": model.get("name") or mid, "free": True, "via": "openrouter"})
    out.append({"id": PAID_MODEL, "name": PAID_NAME, "free": False, "via": "openrouter"})
    return out


def _get_models(url: str, key: str) -> list:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = httpx.get(f"{reach_url(url)}/models", headers=headers, timeout=20)
    r.raise_for_status()
    return r.json().get("data") or []


def catalog(settings) -> list[dict]:
    if settings.openrouter_stub:
        return list(_STUB_MODELS)
    global _CACHE
    ts, items = _CACHE
    want_local = bool((settings.openai_base_url or "").strip())
    if items and time.time() - ts < 3600 and (not want_local or any(m.get("via") == "openai" for m in items)):
        return items
    prev_local = [m for m in items if m.get("via") == "openai"]
    local = []
    if want_local:
        try:
            local = openai_models(_get_models(settings.openai_base_url, settings.openai_api_key))
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            local = prev_local
    try:
        items = pick_models(_get_models(settings.openrouter_base_url, settings.openrouter_api_key))
    except (httpx.HTTPError, ValueError, TypeError):
        items = list(_STUB_MODELS)
    seen = {m["id"] for m in local}
    items = local + [m for m in items if m["id"] not in seen]
    _CACHE = (time.time(), items)
    return items


def resolve_model(model, settings) -> str:
    cats = catalog(settings)
    ids = {m["id"] for m in cats}
    chosen = (model or "").strip() or settings.openrouter_model
    if chosen not in ids:
        raise ValueError("model not allowed")
    return chosen


def resolve_effort(effort) -> str:
    chosen = (effort or "none").strip().lower() or "none"
    if chosen not in EFFORTS:
        raise ValueError("bad effort")
    return chosen


def make_client(settings, model=None):
    # ponytail: placeholder so uvicorn can boot without a key; real calls still 401
    ou = (settings.openai_base_url or "").strip()
    if ou and model and any(m["id"] == model and m.get("via") == "openai" for m in catalog(settings)):
        return OpenAI(base_url=reach_url(ou), api_key=settings.openai_api_key or "local", timeout=300)
    return OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key or "missing",
        timeout=90,
    )


def pg_error(e: BaseException, ms: int | None = None) -> ValueError:
    primary = getattr(getattr(e, "diag", None), "message_primary", None) or str(e).split("\n")[0]
    low = primary.lower()
    if "canceling statement" in low or "statement timeout" in low:
        budget = f"{ms}ms" if ms is not None else "time limit"
        return ValueError(
            f"path blocked: exceeded {budget} (likely a full scan). "
            "Do not retry this SQL. Equality or prefix LIKE on an id column, or a different table."
        )
    return ValueError(primary)


def _pg_rows(settings, sql, params=None, db_key: str = "hub", statement_timeout_ms: int = 5000):
    conn = pg_connect(settings, db_key, statement_timeout_ms=statement_timeout_ms)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        if type(e).__module__.startswith("psycopg"):
            raise pg_error(e, statement_timeout_ms) from e
        raise
    finally:
        conn.close()


_TABLE = re.compile(r"\b((?:[a-z_][\w]*\.)+[a-z_][\w]*)\b", re.I)
_TOK = re.compile(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]+")


def cookbook_clause(rows, question="") -> str:
    # ponytail: lexical overlap over approved catalog; FTS5 if list_sql is slow
    q = set(_TOK.findall((question or "").lower()))
    ranked = []
    for r in rows or []:
        blob = f"{r.get('note') or ''} {r.get('sql') or ''} {r.get('db') or ''}"
        hit = len(q & set(_TOK.findall(blob.lower()))) if q else 0
        if not hit:
            continue
        ranked.append((hit, r))
    ranked.sort(key=lambda x: -x[0])
    bits = []
    for _, r in ranked[:6]:
        note = re.sub(r"\s+", " ", (r.get("note") or "").strip())[:120]
        tables = ", ".join(list(dict.fromkeys(_TABLE.findall(r.get("sql") or "")))[:4])
        db = r.get("db") or "hub"
        line = f"- [{db}] {note}" + (f" · {tables}" if tables else "")
        if line.strip(" -[]"):
            bits.append(line)
    if not bits:
        return ""
    return "\n## Approved SQL from history (prefer these paths)\n" + "\n".join(bits)


def note_from_sql(sql: str) -> str:
    keys = list(dict.fromkeys(re.findall(r"\{\{([A-Za-z_]\w*)\}\}", sql or "")))
    aliases = list(dict.fromkeys(re.findall(r'\bAS\s+"?([A-Za-z_]\w*)"?', sql or "", re.I)))
    outs = [a for a in aliases if a not in keys]
    return f"Input: {', '.join(keys) or '-'}\nOutput: {', '.join(outs) or '-'}"


def sheet_column_clause(names) -> str:
    cols = sheet_cols(names)
    if not cols:
        return ""
    places = ", ".join("{{" + c + "}}" for c in cols)
    return (
        "\nSheet columns (names only): "
        + ", ".join(cols)
        + f". For sheet values write {places} in SQL, never real cell values. "
        "If which sheet column to look up is unclear, ask_question with those names as options. "
        "Never ask the user to type RP ids, emails, or staff numbers. "
        "SELECT aliases must match these names exactly (case-sensitive). "
        "Unknown aliases become new Grist columns on write; do not ask_question just to add a column."
    )


_VALUE_ASK = re.compile(r"(请提供|provide).*(RP|编号|email|工号)|rp0\d{2,}|comma.separat|逗号分隔", re.I)


def sheet_cols(names) -> list[str]:
    cols = []
    for n in names or []:
        if isinstance(n, str) and _COL_ID.match(n) and n not in _SKIP_COLS and n not in cols:
            cols.append(n)
        if len(cols) >= 40:
            break
    return cols


def ask_wants_values(args, columns) -> bool:
    if not sheet_cols(columns):
        return False
    q = str((args or {}).get("question") or "")
    return bool(_VALUE_ASK.search(q))


def ask_from_text(text, columns) -> dict | None:
    t = (text or "").strip()
    if not t or t == "No SQL returned.":
        return None
    if not (t.endswith("?") or t.endswith("？") or "请问" in t or "哪一列" in t or "which column" in t.lower()):
        return None
    args: dict = {"question": t, "kind": "single"}
    cols = sheet_cols(columns)
    if cols:
        args["options"] = cols
    return {"id": "ask-from-text", "name": "ask_question", "arguments": args}


def preview_sheet_error(sql: str, columns) -> str | None:
    cols = sheet_cols(columns)
    if not cols:
        return None
    if any("{{" + c + "}}" in (sql or "") for c in cols):
        return None
    shown = ", ".join("{{" + c + "}}" for c in cols[:8])
    return f"Use a sheet placeholder ({shown}), never a literal id."


def _db_key(arguments: dict | None) -> str:
    key = (arguments or {}).get("db") or "hub"
    return key if key in ("hub", "dspace") else "hub"


def propose_sql(sql: str, db_key: str = "hub") -> dict:
    gated = gate_select(sql_for_gate(sql))
    # ponytail: keep {{Email}} for the user to bind at exec; LIMIT is applied on exec
    return {"sql": sql if "{{" in sql else gated, "db": db_key}


def explain_sql(sql: str, settings, db_key: str = "hub") -> str | None:
    # ponytail: placeholders → NULL; real binds still happen when the user execs
    if not settings.upstream_db_host:
        return None
    raw = select_lookup_cols(sql) if "{{" in (sql or "") else sql
    gated = gate_select(sql_for_gate(raw))
    try:
        _pg_rows(settings, "EXPLAIN " + gated, db_key=db_key)
    except Exception as e:
        return str(e)
    return None


def _scalar(v):
    if isinstance(v, (list, tuple)):
        for x in v:
            if x not in (None, ""):
                return str(x)
        return None
    return v


def exec_sql(sql: str, settings, db_key: str = "hub", binds: dict | None = None) -> dict:
    if binds is not None and not isinstance(binds, dict):
        raise ValueError("bad binds")
    if "{{" in (sql or ""):
        sql = bind_placeholders(select_lookup_cols(sql), binds)
    gated = gate_select(sql)
    if not settings.upstream_db_host:
        binds = binds or {}
        keys = [k for k, v in binds.items() if isinstance(v, list) and v]
        if keys:
            n = max(len(binds[k]) for k in keys)
            rows = []
            for i in range(n):
                row = {k: str(binds[k][i]) for k in keys if i < len(binds[k]) and binds[k][i] not in (None, "")}
                if row:
                    row.setdefault("Name", "e2e-sql")
                    rows.append(row)
            if rows:
                return {"sql": gated, "rows": rows, "truncated": 0, "db": db_key}
        return {"sql": gated, "rows": [{"Email": "new@hku.hk", "Name": "New"}], "truncated": 0, "db": db_key}
    # ponytail: first array element; pick a preferred email if users need it
    rows = [
        {k: _scalar(v) for k, v in row.items()}
        for row in _pg_rows(settings, gated, db_key=db_key, statement_timeout_ms=30000)
    ]
    return {"sql": gated, "rows": rows, "truncated": 0, "db": db_key}


def _clip(v, n: int = 80):
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def is_local_client(settings, client) -> bool:
    ou = (settings.openai_base_url or "").strip()
    return bool(ou and client is not None and reach_url(ou) in str(getattr(client, "base_url", "") or ""))


def execute_tool(name: str, arguments: dict, settings, *, explore: bool = False):
    db_key = _db_key(arguments)
    table_limit = 200 if explore else 50
    if name == "list_tables":
        if not settings.upstream_db_host:
            return [{"table": "personnel.hubappt"}]
        return _pg_rows(
            settings,
            "SELECT table_schema || '.' || table_name AS table "
            "FROM information_schema.tables "
            f"WHERE table_schema NOT IN ('pg_catalog','information_schema') LIMIT {table_limit}",
            db_key=db_key,
        )
    if name == "describe_table":
        table = (arguments.get("table") or "").split(".")[-1]
        if not settings.upstream_db_host:
            return [{"name": "email", "type": "text"}, {"name": "name", "type": "text"}]
        return _pg_rows(
            settings,
            "SELECT column_name AS name, data_type AS type "
            "FROM information_schema.columns WHERE table_name = %s LIMIT 50",
            (table,),
            db_key=db_key,
        )
    if name == "preview_sql":
        sql = arguments.get("sql") or ""
        proposed = propose_sql(sql, db_key=db_key)
        err = explain_sql(sql, settings, db_key)
        if err:
            return {"error": err}
        if explore and settings.upstream_db_host:
            try:
                gated = gate_select(sql_for_gate(sql), limit=5)
                rows = [
                    {k: _clip(_scalar(v)) for k, v in row.items()}
                    for row in _pg_rows(settings, gated, db_key=db_key)
                ]
                # ponytail: {{}} binds NULL here; empty is not a miss until the widget execs
                if not rows and "{{" not in (sql or ""):
                    return {
                        "error": "0 rows. Not found. Tell the user in one sentence or try another table/db. Do not offer this SQL."
                    }
                proposed = {**proposed, "sample": rows[:5]}
                if not rows:
                    proposed = {**proposed, "note": "empty sample: placeholders were NULL, not a miss"}
            except Exception as e:
                return {"error": str(e)}
        return proposed
    raise ValueError(name)


def stub_turn(tool_results, settings) -> dict:
    if tool_results:
        # ponytail: Email is MemoryGrist.upsert's key; {ok:1} is dropped and /submit shows []
        return {
            "text": None,
            "tool_calls": [],
            "previews": [
                {
                    "sql": 'SELECT {{Email}} AS "Email", \'e2e-sql\' AS "Name"',
                    "db": "hub",
                }
            ],
            "tools": [],
        }
    return {
        "text": None,
        "tool_calls": [
            {
                "id": "stub-ask",
                "name": "ask_question",
                "arguments": {
                    "question": "Which source?",
                    "kind": "single",
                    "options": ["staff", "scopus"],
                },
            }
        ],
        "previews": [],
        "tools": [],
    }


def _parse_args(tc) -> dict:
    raw = tc.function.arguments
    if isinstance(raw, dict):
        return raw
    return json.loads(raw or "{}")


def _reasoning(msg) -> str:
    extra = getattr(msg, "model_extra", None) or {}
    dumped = extra if isinstance(extra, dict) else {}
    dump = getattr(msg, "model_dump", None)
    if callable(dump):
        try:
            dumped = {**dumped, **(dump() or {})}
        except Exception:
            pass
    for v in (
        getattr(msg, "reasoning", None),
        getattr(msg, "reasoning_content", None),
        dumped.get("reasoning"),
        dumped.get("reasoning_content"),
    ):
        if isinstance(v, str) and v.strip():
            return v.strip()
    bits = []
    for d in dumped.get("reasoning_details") or getattr(msg, "reasoning_details", None) or []:
        if isinstance(d, dict):
            t = d.get("text") or d.get("summary")
            if isinstance(t, str) and t.strip():
                bits.append(t.strip())
    return "\n\n".join(bits)


def _result(text, thoughts, tool_calls, previews, tools=None) -> dict:
    return {
        "text": text,
        "reasoning": "\n\n".join(thoughts) or None,
        "tool_calls": tool_calls,
        "previews": previews,
        "tools": tools or [],
    }


def _tool_item(name, args, out) -> dict:
    return {
        "name": name,
        "arguments": args,
        "output": _clip(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False), 4000),
    }


def _delta_reasoning(delta) -> str:
    if delta is None:
        return ""
    for key in ("reasoning", "reasoning_content"):
        v = getattr(delta, key, None)
        if isinstance(v, str) and v:
            return v
    extra = getattr(delta, "model_extra", None)
    if isinstance(extra, dict):
        for key in ("reasoning", "reasoning_content"):
            v = extra.get(key)
            if isinstance(v, str) and v:
                return v
    return ""


def _complete(client, kwargs):
    # ponytail: stream=True; non-stream mocks still return .choices
    try:
        resp = client.chat.completions.create(**kwargs, stream=True)
    except Exception as e:
        if "stream" not in str(e).lower():
            raise
        resp = client.chat.completions.create(**kwargs)
    if getattr(resp, "choices", None) is not None:
        msg = resp.choices[0].message
        think = _reasoning(msg)
        if think:
            yield {"think": think}
        yield {"msg": msg}
        return
    think = ""
    content = ""
    tcs: dict[int, dict] = {}
    for chunk in resp:
        choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
        if not choice:
            continue
        delta = getattr(choice, "delta", None)
        bit = _delta_reasoning(delta)
        if bit:
            think += bit
            yield {"think": think}
        if delta is None:
            continue
        if getattr(delta, "content", None):
            content += delta.content
        for part in getattr(delta, "tool_calls", None) or []:
            i = getattr(part, "index", 0)
            slot = tcs.setdefault(i, {"id": "", "name": "", "args": ""})
            if getattr(part, "id", None):
                slot["id"] = part.id
            fn = getattr(part, "function", None)
            if fn is None:
                continue
            if getattr(fn, "name", None):
                slot["name"] = fn.name
            if getattr(fn, "arguments", None):
                slot["args"] += fn.arguments
    yield {
        "msg": SimpleNamespace(
            content=content,
            reasoning=think,
            tool_calls=[
                SimpleNamespace(id=s["id"], function=SimpleNamespace(name=s["name"], arguments=s["args"]))
                for _, s in sorted(tcs.items())
            ]
            or None,
            model_extra={},
        )
    }


def iter_turn(*, client, settings, messages, tool_results, model=None, effort="none", sheet_columns=None, cookbook=""):
    if settings.openrouter_stub == "ask":
        yield {"type": "done", **stub_turn(tool_results, settings)}
        return
    local = is_local_client(settings, client)
    system = (LOCAL_SYSTEM if local else SYSTEM) + sheet_column_clause(sheet_columns) + (cookbook or "")
    msgs = [{"role": "system", "content": system}, *list(messages or [])]
    for tr in tool_results or []:
        msgs.append({"role": "tool", "tool_call_id": tr["id"], "content": tr.get("output") or ""})
    extra = {} if effort == "none" else {"reasoning": {"effort": effort}}
    previews = []
    last_err = None
    thoughts = []
    tools_used = []

    def done(text, tool_calls):
        return {"type": "done", **_result(text, thoughts, tool_calls, previews, tools_used)}

    try:
        for _ in range(12 if local else 6):
            kwargs = {"model": model or settings.openrouter_model, "messages": msgs, "tools": TOOLS}
            if extra and not local:
                kwargs["extra_body"] = extra
            round_think = ""
            msg = None
            for ev in _complete(client, kwargs):
                if "think" in ev:
                    round_think = ev["think"]
                    yield {"type": "reasoning", "text": "\n\n".join([*thoughts, round_think])}
                else:
                    msg = ev["msg"]
            think = round_think or (_reasoning(msg) if msg else "")
            if think and (not thoughts or thoughts[-1] != think):
                thoughts.append(think)
            if think and not round_think:
                yield {"type": "reasoning", "text": "\n\n".join(thoughts)}
            if msg is None:
                yield done("empty completion", [])
                return
            tcs = msg.tool_calls or []
            if not tcs:
                text = (msg.content or "").strip() or None
                ask = ask_from_text(text, sheet_columns) if text and not previews else None
                if ask:
                    yield done(text, [ask])
                    return
                if not previews and not text:
                    text = last_err or "No SQL returned."
                yield done(text, [])
                return
            asks = []
            executed = []
            for tc in tcs:
                name = tc.function.name
                args = _parse_args(tc)
                if name == "ask_question":
                    if ask_wants_values(args, sheet_columns):
                        out = {
                            "error": "Do not ask for cell values. Call preview_sql with {{ColId}} from the sheet."
                        }
                        idx = len(tools_used)
                        tools_used.append(_tool_item(name, args, out))
                        yield {"type": "tool", "index": idx, **tools_used[idx]}
                        executed.append((tc, json.dumps(out)))
                        continue
                    asks.append({"id": tc.id, "name": name, "arguments": args})
                    continue
                idx = len(tools_used)
                tools_used.append({"name": name, "arguments": args, "output": ""})
                yield {"type": "tool", "index": idx, "name": name, "arguments": args, "output": ""}
                try:
                    out = execute_tool(name, args, settings, explore=local)
                except Exception as e:
                    out = {"error": str(e)}
                if name == "preview_sql" and isinstance(out, dict) and not out.get("error"):
                    err = preview_sheet_error(out.get("sql") or "", sheet_columns)
                    if err:
                        out = {"error": err}
                if isinstance(out, dict) and out.get("error"):
                    last_err = str(out["error"])
                if name == "preview_sql" and isinstance(out, dict) and out.get("sql") and not out.get("error"):
                    previews[:] = [{"sql": out["sql"], "db": out.get("db") or "hub"}]
                tools_used[idx] = _tool_item(name, args, out)
                yield {"type": "tool", "index": idx, **tools_used[idx]}
                executed.append((tc, json.dumps(out)))
            if asks:
                yield done((msg.content or "").strip() or None, asks)
                return
            asst = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                            if isinstance(tc.function.arguments, str)
                            else json.dumps(tc.function.arguments),
                        },
                    }
                    for tc, _ in executed
                ],
            }
            if think:
                asst["reasoning"] = think
            details = getattr(msg, "reasoning_details", None)
            if details is None and isinstance(getattr(msg, "model_extra", None), dict):
                details = msg.model_extra.get("reasoning_details")
            if details:
                asst["reasoning_details"] = details
            msgs.append(asst)
            for tc, content in executed:
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    except Exception as e:
        yield done(str(e), [])
        return
    yield done(last_err if not previews else None, [])


def run_turn(*, client, settings, messages, tool_results, model=None, effort="none", sheet_columns=None, cookbook="") -> dict:
    result = _result(None, [], [], [])
    for ev in iter_turn(
        client=client,
        settings=settings,
        messages=messages,
        tool_results=tool_results,
        model=model,
        effort=effort,
        sheet_columns=sheet_columns,
        cookbook=cookbook,
    ):
        if ev.get("type") == "done":
            result = {k: ev.get(k) for k in result}
    return result
