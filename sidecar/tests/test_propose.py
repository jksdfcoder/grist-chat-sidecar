from app.propose import ColumnMap, propose_csv

LIVE = "Email,Name,Faculty\na@hku.hk,Old,Science\nc@hku.hk,Keep,Arts\n"
GRIST = [
    {"Email": "a@hku.hk", "Name": "New", "Faculty": "ShouldNotWrite"},
    {"Email": "b@hku.hk", "Name": "Bob", "Faculty": "Med"},
    {"Email": "  ", "Name": "Nope", "Faculty": "X"},
]
MAP = ColumnMap(key_grist="Email", key_csv="Email", columns=[("Email", "Email"), ("Name", "Name")])

def test_update_append_keep_no_delete():
    r = propose_csv(LIVE, GRIST, MAP)
    assert any("empty key" in w.lower() or "empty" in w.lower() for w in r.warnings)
    lines = [ln for ln in r.csv_text.strip().splitlines()]
    assert lines[0] == "Email,Name,Faculty"
    body = "\n".join(lines[1:])
    assert "a@hku.hk,New,Science" in body
    assert "c@hku.hk,Keep,Arts" in body
    assert "b@hku.hk,Bob," in body or "b@hku.hk,Bob,\"\"" in body
    kinds = {h["key"]: h["kind"] for h in r.hunks}
    assert kinds["a@hku.hk"] == "update"
    assert kinds["b@hku.hk"] == "append"
    assert "c@hku.hk" not in kinds or kinds.get("c@hku.hk") == "keep"
