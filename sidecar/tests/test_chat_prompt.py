from app.chat import SYSTEM, PAID_MODEL, execute_tool, pick_models, resolve_effort, stub_turn


def test_system_prompt_has_join_map():
    assert "personnel.hubappt" in SYSTEM
    assert "scopusauthorid" in SYSTEM
    assert 'db: "dspace"' in SYSTEM or "db: \"dspace\"" in SYSTEM
    assert "never see row" in SYSTEM
    assert "Always call preview_sql" in SYSTEM
    assert "closing sentence" in SYSTEM
    assert "Never ask the user to type" in SYSTEM
    assert "{{RP_no}}" in SYSTEM
    assert "WOS" in SYSTEM
    assert "hub.wos_publications" in SYSTEM
    assert "EXPLAIN" in SYSTEM
    assert "array_to_string" in SYSTEM
    assert "One row per" in SYSTEM
    assert "staff_number::text" in SYSTEM
    assert "v.crisid IN" in SYSTEM
    assert "path blocked" in SYSTEM


def test_rejects_leading_wildcard_like():
    from app.sql_gate import gate_select

    try:
        gate_select("SELECT 1 FROM t WHERE x ILIKE '%001%'")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "full table scan" in str(e)
    out = gate_select("SELECT 1 FROM t WHERE x LIKE 'WOS:%'")
    assert "LIKE" in out.upper()


def test_local_system_explores_instead_of_closed_intents():
    from app.chat import LOCAL_SYSTEM

    assert "not limited" in LOCAL_SYSTEM.lower() or "not a closed list" in LOCAL_SYSTEM
    assert "list_tables" in LOCAL_SYSTEM
    assert "describe_table" in LOCAL_SYSTEM
    assert "sample" in LOCAL_SYSTEM
    assert "What users can ask" not in LOCAL_SYSTEM
    assert "personnel.hubappt" in LOCAL_SYSTEM
    assert "WOS" in LOCAL_SYSTEM
    assert "path blocked" in LOCAL_SYSTEM
    assert "0 rows" in LOCAL_SYSTEM
    assert "not a miss" in LOCAL_SYSTEM


def test_sheet_column_clause_names_only():
    from app.chat import sheet_column_clause

    text = sheet_column_clause(["Email", "RP_no", "id", "bad-name", "x;drop", 1])
    assert "{{RP_no}}" in text
    assert "{{Email}}" in text
    assert "{{id}}" not in text
    assert "Never ask the user to type" in text
    assert "new Grist columns" in text
    assert "bad-name" not in text
    assert "drop" not in text.lower()
    assert sheet_column_clause([]) == ""


def test_pick_models_free_tools_plus_paid():
    out = pick_models(
        [
            {
                "id": "a:free",
                "name": "A",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["tools"],
            },
            {
                "id": "b:free",
                "name": "B",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": [],
            },
            {
                "id": "openai/gpt-4",
                "name": "GPT",
                "pricing": {"prompt": "1", "completion": "1"},
                "supported_parameters": ["tools"],
            },
        ]
    )
    assert [m["id"] for m in out] == ["a:free", PAID_MODEL]


def test_openai_models_vllm_payload():
    from app.chat import openai_models

    out = openai_models([{"id": "qwen3.8-27b", "object": "model", "owned_by": "vllm"}])
    assert out == [{"id": "qwen3.8-27b", "name": "qwen3.8-27b", "free": True, "via": "openai"}]


def test_catalog_prepends_local_and_routes_client(monkeypatch):
    from app import chat
    from app.settings import Settings

    chat._CACHE = (0.0, [])

    def fake_get(url, headers=None, timeout=None):
        class R:
            def raise_for_status(self):
                return None

            def json(self):
                if "openrouter" in url:
                    return {"data": []}
                return {"data": [{"id": "qwen3.8-27b", "object": "model"}]}

        return R()

    monkeypatch.setattr(chat.httpx, "get", fake_get)
    s = Settings.model_validate(
        {
            "sqlite_path": ":memory:",
            "openai_base_url": "http://127.0.0.1:25890/v1",
            "openai_api_key": "sk-test",
            "openrouter_base_url": "https://openrouter.ai/api/v1",
        }
    )
    ids = [m["id"] for m in chat.catalog(s)]
    assert ids[0] == "qwen3.8-27b"
    assert PAID_MODEL in ids
    local = chat.make_client(s, "qwen3.8-27b")
    assert "25890" in str(local.base_url)
    assert local.timeout == 300
    remote = chat.make_client(s, PAID_MODEL)
    assert "openrouter" in str(remote.base_url)
    chat._CACHE = (0.0, [])


def test_catalog_keeps_local_when_vllm_drops(monkeypatch):
    import httpx
    from app import chat
    from app.settings import Settings

    chat._CACHE = (0.0, [])
    n = {"local": 0}

    def fake_get(url, headers=None, timeout=None):
        class R:
            def raise_for_status(self):
                return None

            def json(self):
                if "openrouter" in url:
                    return {"data": []}
                return {"data": [{"id": "qwen3.8-27b", "object": "model"}]}

        if "25890" in url:
            n["local"] += 1
            if n["local"] > 1:
                raise httpx.ConnectError("down")
        return R()

    monkeypatch.setattr(chat.httpx, "get", fake_get)
    s = Settings.model_validate(
        {
            "sqlite_path": ":memory:",
            "openai_base_url": "http://127.0.0.1:25890/v1",
            "openai_api_key": "sk-test",
            "openrouter_base_url": "https://openrouter.ai/api/v1",
        }
    )
    assert chat.catalog(s)[0]["id"] == "qwen3.8-27b"
    chat._CACHE = (0.0, chat._CACHE[1])
    assert chat.catalog(s)[0]["id"] == "qwen3.8-27b"
    chat._CACHE = (0.0, [])


def test_resolve_effort_rejects_unknown():
    assert resolve_effort("") == "none"
    try:
        resolve_effort("ultra")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_preview_sql_tool_returns_no_rows():
    from app.settings import Settings

    s = Settings.model_validate({"sqlite_path": ":memory:"})
    out = execute_tool("preview_sql", {"sql": "SELECT 1 AS ok", "db": "hub"}, s)
    assert "rows" not in out
    assert "error" not in out
    assert "LIMIT" in out["sql"].upper()
    stub = stub_turn([{"id": "x"}], s)
    assert "rows" not in stub["previews"][0]
    assert "{{Email}}" in stub["previews"][0]["sql"]


def test_local_preview_sql_includes_clipped_sample(monkeypatch):
    from app import chat
    from app.settings import Settings

    s = Settings.model_validate({"sqlite_path": ":memory:", "upstream_db_host": "db.example"})
    seen = []

    def fake_rows(_settings, sql, params=None, db_key="hub"):
        seen.append(sql)
        if str(sql).upper().startswith("EXPLAIN"):
            return []
        return [{"email": "a" * 90, "n": 1}]

    monkeypatch.setattr(chat, "_pg_rows", fake_rows)
    out = chat.execute_tool("preview_sql", {"sql": "SELECT 1 AS ok", "db": "hub"}, s, explore=True)
    assert "sample" in out
    assert len(out["sample"][0]["email"]) == 80
    assert out["sample"][0]["email"].endswith("…")
    remote = chat.execute_tool("preview_sql", {"sql": "SELECT 1 AS ok", "db": "hub"}, s)
    assert "sample" not in remote


def test_local_preview_sql_timeout_is_error(monkeypatch):
    from app import chat
    from app.settings import Settings

    s = Settings.model_validate({"sqlite_path": ":memory:", "upstream_db_host": "db.example"})

    def fake_rows(_settings, sql, params=None, db_key="hub"):
        if str(sql).upper().startswith("EXPLAIN"):
            return []
        raise ValueError(
            "path blocked: exceeded 5000ms (likely a full scan). "
            "Do not retry this SQL. Equality or prefix LIKE on an id column, or a different table."
        )

    monkeypatch.setattr(chat, "_pg_rows", fake_rows)
    out = chat.execute_tool("preview_sql", {"sql": "SELECT 1 AS ok", "db": "hub"}, s, explore=True)
    assert out["error"].startswith("path blocked")
    assert "sql" not in out


def test_local_preview_empty_sample_without_placeholder_is_miss(monkeypatch):
    from app import chat
    from app.settings import Settings

    s = Settings.model_validate({"sqlite_path": ":memory:", "upstream_db_host": "db.example"})

    def fake_rows(_settings, sql, params=None, db_key="hub"):
        return []

    monkeypatch.setattr(chat, "_pg_rows", fake_rows)
    out = chat.execute_tool("preview_sql", {"sql": "SELECT 1 FROM t WHERE id = 0", "db": "hub"}, s, explore=True)
    assert "0 rows" in out["error"]
    assert "sql" not in out
    keep = chat.execute_tool(
        "preview_sql", {"sql": "SELECT {{Email}} AS email FROM t", "db": "hub"}, s, explore=True
    )
    assert "error" not in keep
    assert keep.get("sample") == []


def test_preview_sql_explain_error_is_not_a_preview(monkeypatch):
    from app import chat
    from app.settings import Settings

    s = Settings.model_validate({"sqlite_path": ":memory:", "upstream_db_host": "db.example"})
    seen = []

    def boom(_settings, sql, params=None, db_key="hub"):
        seen.append(sql)
        raise ValueError("operator does not exist: integer = character varying")

    monkeypatch.setattr(chat, "_pg_rows", boom)
    out = chat.execute_tool("preview_sql", {"sql": "SELECT 1 AS ok", "db": "hub"}, s)
    assert out == {"error": "operator does not exist: integer = character varying"}
    assert seen and seen[0].upper().startswith("EXPLAIN")


def test_explain_sql_skips_without_host():
    from app.chat import explain_sql
    from app.settings import Settings

    s = Settings.model_validate({"sqlite_path": ":memory:", "upstream_db_host": ""})
    assert explain_sql("SELECT 1 AS ok", s, "hub") is None


def test_note_from_sql_is_column_names():
    from app.chat import note_from_sql

    note = note_from_sql(
        'SELECT v.crisid AS "RP_no", v.fullname AS "Name", e.email AS "Email" WHERE v.crisid IN ({{RP_no}})'
    )
    assert note == "Input: RP_no\nOutput: Name, Email"


def test_cookbook_clause_skips_author_and_caps():
    from app.chat import cookbook_clause

    rows = [
        {
            "db": "hub",
            "note": "WOS accession",
            "sql": "SELECT id FROM hub.wos_publications WHERE ut = {{UT}}",
            "author": "someone@hku.hk",
        },
        {
            "db": "dspace",
            "note": "staff email lookup",
            "sql": "SELECT email FROM personnel.hubappt WHERE email IN ({{Email}})",
            "author": "someone@hku.hk",
        },
    ]
    text = cookbook_clause(rows, "WOS:001425402200001 哪些 RP")
    assert "Approved SQL" in text
    assert "wos_publications" in text
    assert "hubappt" not in text
    assert "@hku.hk" not in text
    assert "SELECT" not in text
    assert cookbook_clause(rows, "unrelated xyzabc") == ""
    assert cookbook_clause([], "WOS") == ""


def test_empty_model_reply_is_not_silent():
    from app.chat import run_turn
    from app.settings import Settings

    class _Client:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **_kwargs):
            class _Msg:
                content = "   "
                tool_calls = None

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp()

    s = Settings.model_validate({"sqlite_path": ":memory:", "openrouter_stub": ""})
    out = run_turn(
        client=_Client(),
        settings=s,
        messages=[{"role": "user", "content": "hi"}],
        tool_results=[],
    )
    assert out["text"] == "No SQL returned."
    assert out["reasoning"] is None
    assert out["previews"] == []
    assert out["tool_calls"] == []
    assert out["tools"] == []


def test_preview_keeps_text_and_reasoning():
    from types import SimpleNamespace

    from app.chat import run_turn
    from app.settings import Settings

    n = {"i": 0}

    class _Client:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **_kwargs):
            i = n["i"]
            n["i"] += 1
            if i == 0:
                tc = SimpleNamespace(
                    id="1",
                    function=SimpleNamespace(
                        name="preview_sql",
                        arguments='{"sql":"SELECT 1 AS ok","db":"hub"}',
                    ),
                )
                msg = SimpleNamespace(content="", reasoning="plan", tool_calls=[tc])
            else:
                msg = SimpleNamespace(content="done", reasoning="check", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    s = Settings.model_validate({"sqlite_path": ":memory:", "openrouter_stub": ""})
    out = run_turn(
        client=_Client(),
        settings=s,
        messages=[{"role": "user", "content": "hi"}],
        tool_results=[],
    )
    assert out["text"] == "done"
    assert out["reasoning"] == "plan\n\ncheck"
    assert out["previews"]
    assert [t["name"] for t in out["tools"]] == ["preview_sql"]
    assert out["tools"][0]["arguments"]["sql"] == "SELECT 1 AS ok"
    assert "SELECT 1" in out["tools"][0]["output"]


def test_run_turn_collects_list_tables_then_preview():
    from types import SimpleNamespace

    from app.chat import run_turn
    from app.settings import Settings

    n = {"i": 0}

    class _Client:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **_kwargs):
            i = n["i"]
            n["i"] += 1
            if i == 0:
                tc = SimpleNamespace(
                    id="1",
                    function=SimpleNamespace(name="list_tables", arguments='{"db":"hub"}'),
                )
                msg = SimpleNamespace(content="", tool_calls=[tc])
            elif i == 1:
                tc = SimpleNamespace(
                    id="2",
                    function=SimpleNamespace(
                        name="preview_sql",
                        arguments='{"sql":"SELECT 1 AS ok","db":"hub"}',
                    ),
                )
                msg = SimpleNamespace(content="", tool_calls=[tc])
            else:
                msg = SimpleNamespace(content="done", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    s = Settings.model_validate({"sqlite_path": ":memory:", "openrouter_stub": ""})
    out = run_turn(
        client=_Client(),
        settings=s,
        messages=[{"role": "user", "content": "hi"}],
        tool_results=[],
    )
    assert [t["name"] for t in out["tools"]] == ["list_tables", "preview_sql"]
    assert out["tools"][0]["arguments"]["db"] == "hub"
    assert out["tools"][0]["output"].startswith("[")


def test_iter_turn_emits_tool_start_before_output():
    from types import SimpleNamespace

    from app.chat import iter_turn
    from app.settings import Settings

    n = {"i": 0}

    class _Client:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **_kwargs):
            i = n["i"]
            n["i"] += 1
            if i == 0:
                tc = SimpleNamespace(
                    id="1",
                    function=SimpleNamespace(name="list_tables", arguments='{"db":"hub"}'),
                )
                msg = SimpleNamespace(content="", reasoning="look up tables", tool_calls=[tc])
            else:
                msg = SimpleNamespace(content="done", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    s = Settings.model_validate({"sqlite_path": ":memory:", "openrouter_stub": ""})
    events = list(
        iter_turn(
            client=_Client(),
            settings=s,
            messages=[{"role": "user", "content": "hi"}],
            tool_results=[],
        )
    )
    assert events[0]["type"] == "reasoning"
    assert events[1]["type"] == "tool" and events[1]["output"] == ""
    assert events[2]["type"] == "tool" and events[2]["output"]
    assert events[-1]["type"] == "done"
    assert events[-1]["tools"][0]["name"] == "list_tables"


def test_iter_turn_streams_reasoning_before_tools():
    from types import SimpleNamespace

    from app.chat import iter_turn
    from app.settings import Settings

    def chunk(reasoning="", arguments=None, name=None, cid=None):
        fn = SimpleNamespace(name=name, arguments=arguments) if name or arguments else None
        tc = [SimpleNamespace(index=0, id=cid, function=fn)] if fn or cid else None
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(reasoning=reasoning or None, content=None, tool_calls=tc))]
        )

    class _Client:
        def __init__(self):
            self.chat = self
            self.completions = self
            self.n = 0

        def create(self, **kwargs):
            assert kwargs.get("stream") is True
            i = self.n
            self.n += 1
            if i == 0:
                return iter(
                    [
                        chunk(reasoning="plan "),
                        chunk(reasoning="ahead"),
                        chunk(cid="1", name="list_tables", arguments='{"db":"hub"}'),
                    ]
                )
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=None))])

    s = Settings.model_validate({"sqlite_path": ":memory:", "openrouter_stub": ""})
    events = list(
        iter_turn(
            client=_Client(),
            settings=s,
            messages=[{"role": "user", "content": "hi"}],
            tool_results=[],
        )
    )
    thinks = [e["text"] for e in events if e.get("type") == "reasoning"]
    assert thinks[0] == "plan "
    assert thinks[1] == "plan ahead"
    assert events[2]["type"] == "tool" and events[2]["output"] == ""
    assert events[-1]["type"] == "done"


def test_reasoning_from_details():
    from types import SimpleNamespace

    from app.chat import _reasoning

    msg = SimpleNamespace(
        reasoning=None,
        reasoning_content=None,
        model_extra={"reasoning_details": [{"text": "step one"}, {"summary": "step two"}]},
    )
    assert _reasoning(msg) == "step one\n\nstep two"


def test_ask_wants_values_and_literal_sql():
    from app.chat import ask_wants_values, preview_sheet_error

    cols = ["Email", "RP_no"]
    assert ask_wants_values(
        {"question": "请提供您想要查询的 RP 编号（研究人员页面 ID），例如 rp01234。"},
        cols,
    )
    assert not ask_wants_values({"question": "Email or RP_no?", "options": ["Email", "RP_no"]}, cols)
    assert not ask_wants_values({"question": "请提供 RP 编号"}, [])
    assert preview_sheet_error("SELECT v.crisid WHERE v.crisid = 'rp00020'", cols)
    assert preview_sheet_error('SELECT v.crisid AS "RP_no" WHERE v.crisid IN ({{RP_no}})', cols) is None
    assert preview_sheet_error("SELECT 1", []) is None


def test_text_question_becomes_ask():
    from types import SimpleNamespace

    from app.chat import ask_from_text, run_turn
    from app.settings import Settings

    q = "您要找 ORCID，需要用现有列中的一个来查询。请问用哪一列作为查询依据？"
    ask = ask_from_text(q, ["Email", "RP_no", "id"])
    assert ask and ask["name"] == "ask_question"
    assert ask["arguments"]["options"] == ["Email", "RP_no"]
    assert ask_from_text("SELECT is ready.", ["Email"]) is None
    assert ask_from_text(q, [])["arguments"].get("options") is None

    class _Client:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **_kwargs):
            msg = SimpleNamespace(content=q, tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    s = Settings.model_validate({"sqlite_path": ":memory:", "openrouter_stub": ""})
    out = run_turn(
        client=_Client(),
        settings=s,
        messages=[{"role": "user", "content": "找orcid"}],
        tool_results=[],
        sheet_columns=["Email", "RP_no"],
    )
    assert out["tool_calls"][0]["name"] == "ask_question"
    assert out["tool_calls"][0]["arguments"]["options"] == ["Email", "RP_no"]
