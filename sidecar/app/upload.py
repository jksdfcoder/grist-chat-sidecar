import re

from app.azure_csv import summarize_csv
from app.propose import ColumnMap, _csv_rows, ensure_fields, propose_csv

_ID = re.compile(r"^[\w.-]{1,64}$")
_PATH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_COL = re.compile(r"^[A-Za-z_]\w{0,63}$")


def check_dest(dest: str) -> str:
    d = (dest or "azure").strip().lower()
    if d == "db":
        raise ValueError("upstream db upload not yet")
    if d != "azure":
        raise ValueError("bad dest")
    return d


def check_conn(account: str, container: str, path: str) -> tuple[str, str, str]:
    account, container, path = account.strip(), container.strip(), path.strip().lstrip("/")
    if not _ID.match(account) or not _ID.match(container) or not _PATH.match(path) or ".." in path:
        raise ValueError("bad azure conn")
    return account, container, path


def cols(xs) -> list[str]:
    out = []
    for x in xs or []:
        s = str(x)
        if _COL.match(s) and s not in out:
            out.append(s)
        if len(out) >= 40:
            break
    return out


def clean_rows(rows, names: list[str], limit: int = 5000) -> list[dict]:
    out = []
    for r in (rows or [])[:limit]:
        if not isinstance(r, dict):
            continue
        out.append({c: "" if r.get(c) is None else str(r.get(c))[:8000] for c in names})
    return out


def key_for_path(store, account: str, container: str, path: str, body: dict) -> str:
    key = (body.get("account_key") or "").strip()
    if key:
        return key
    if body.get("template_id"):
        t = store.get_template(int(body["template_id"]))
        if t:
            return t["account_key"]
    for t in store.list_templates():
        if t["account"] == account and t["container"] == container and t["path"] == path:
            full = store.get_template(t["id"])
            if full and full.get("account_key"):
                return full["account_key"]
    raise ValueError("account_key required")


def resolve_conn(body: dict, store) -> tuple[str, str, str, str]:
    key = (body.get("account_key") or "").strip()
    if key:
        account, container, path = check_conn(body.get("account") or "", body.get("container") or "", body.get("path") or "")
        return account, container, key, path
    tid = body.get("template_id")
    if tid:
        t = store.get_template(int(tid))
        if not t:
            raise ValueError("no template")
        return t["account"], t["container"], t["account_key"], t["path"]
    raise ValueError("account_key required")


def map_columns(selected: list[str], remote: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    by = {c.lower(): c for c in remote}
    pairs = []
    fields = list(remote)
    for g in selected:
        c = by.get(g.lower())
        if not c:
            c = g
            if c not in fields:
                fields.append(c)
        pairs.append((g, c))
    return fields, pairs


def default_keys(selected: list[str], remote: list[str]) -> tuple[str, str]:
    for g in selected:
        c = next((x for x in remote if x.lower() == g.lower()), None)
        if c:
            return g, c
        if g.lower() in ("email", "rp_no"):
            return g, c or g
    g = selected[0] if selected else "email"
    return g, next((x for x in remote if x.lower() == g.lower()), g)


def connect(azure) -> dict:
    body, etag = azure.read()
    info = summarize_csv(body)
    return {"etag": etag, **info}


def snapshot_write(store, azure, *, author: str, kind: str, dest: str, account: str, container: str, path: str, new_body: str, columns: list[str], note: str) -> tuple[str, int]:
    live, etag = azure.read()
    hid = store.add_upload_hist(
        author=author, kind=kind, dest=dest, account=account, container=container, path=path,
        etag=etag, body=live, columns=columns, note=note,
    )
    new_etag = azure.write(new_body, if_match=etag)
    return new_etag, hid


def proposed_csv(live: str, rows: list[dict], selected: list[str], key_grist: str, key_csv: str) -> str:
    remote_cols, _rows = _csv_rows(live)
    fields, pairs = map_columns(selected, remote_cols)
    if key_grist not in selected:
        raise ValueError("key column not selected")
    by = {c.lower(): c for c in remote_cols}
    key_csv = by.get(key_csv.lower(), key_csv)
    key_grist_use = next((c for c in selected if c.lower() == key_grist.lower()), key_grist)
    live2 = ensure_fields(live, fields)
    return propose_csv(live2, rows, ColumnMap(key_grist=key_grist_use, key_csv=key_csv, columns=pairs)).csv_text
