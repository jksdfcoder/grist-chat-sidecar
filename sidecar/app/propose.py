import csv
import io
import time
from dataclasses import dataclass

from app.azure_csv import EtagMismatch
from app.pending import ExpiredPending


@dataclass
class ColumnMap:
    key_grist: str
    key_csv: str
    columns: list[tuple[str, str]]


@dataclass
class ProposeResult:
    csv_text: str
    hunks: list[dict]
    warnings: list[str]
    empty_key_rows: int


def _key(row: dict, col: str) -> str:
    return (row.get(col) or "").strip().lower()


def _csv_rows(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    return list(reader.fieldnames or []), list(reader)


def _write_csv(fieldnames: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def ensure_fields(text: str, fieldnames: list[str]) -> str:
    fields, rows = _csv_rows(text)
    if not fieldnames:
        return text
    merged = list(dict.fromkeys([*fields, *fieldnames]))
    if not fields and not rows:
        return _write_csv(merged, [])
    for r in rows:
        for f in merged:
            r.setdefault(f, "")
    return _write_csv(merged, rows)


def propose_csv(live_csv: str, grist_rows: list[dict], mapping: ColumnMap) -> ProposeResult:
    fieldnames, live_rows = _csv_rows(live_csv)
    warnings: list[str] = []
    empty_key_rows = 0
    grist_by_key: dict[str, dict] = {}
    for g in grist_rows:
        k = _key(g, mapping.key_grist)
        if not k:
            empty_key_rows += 1
            warnings.append("empty key")
            continue
        grist_by_key[k] = g

    hunks: list[dict] = []
    out: list[dict] = []
    seen: set[str] = set()
    for row in live_rows:
        k = _key(row, mapping.key_csv)
        seen.add(k)
        g = grist_by_key.get(k)
        if g is None:
            out.append(row)
            continue
        new_row = dict(row)
        changes = []
        for gcol, ccol in mapping.columns:
            old = new_row.get(ccol) or ""
            new = "" if g.get(gcol) is None else str(g[gcol])
            if old != new:
                changes.append({"column": ccol, "from": old, "to": new})
            new_row[ccol] = new
        out.append(new_row)
        if changes:
            hunks.append({"key": k, "kind": "update", "changes": changes})

    for k, g in grist_by_key.items():
        if k in seen:
            continue
        new_row = {fn: "" for fn in fieldnames}
        changes = []
        for gcol, ccol in mapping.columns:
            new = "" if g.get(gcol) is None else str(g[gcol])
            new_row[ccol] = new
            changes.append({"column": ccol, "from": "", "to": new})
        out.append(new_row)
        hunks.append({"key": k, "kind": "append", "changes": changes})

    return ProposeResult(_write_csv(fieldnames, out), hunks, warnings, empty_key_rows)


def commit_pending(store, azure, *, actor_email, rejected_keys: list[str]) -> str:
    rec = store.get()
    if rec is None or time.time() > rec["expires_at"]:
        raise ExpiredPending
    live, etag = azure.read()
    if etag != rec["etag"]:
        raise EtagMismatch
    text = rec["proposed_csv"]
    if rejected_keys:
        key_csv = rec["map"]["key_csv"]
        rejected = {k.strip().lower() for k in rejected_keys}
        fields, proposed_rows = _csv_rows(text)
        live_by_key = {_key(r, key_csv): r for r in _csv_rows(live)[1]}
        merged = []
        for row in proposed_rows:
            k = _key(row, key_csv)
            if k in rejected:
                if k in live_by_key:
                    merged.append(live_by_key[k])
            else:
                merged.append(row)
        text = _write_csv(fields, merged)
    new_etag = azure.write(text, if_match=etag)
    store.clear()
    return new_etag
