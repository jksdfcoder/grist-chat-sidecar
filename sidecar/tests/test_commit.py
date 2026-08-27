import time
from pathlib import Path
from app.azure_csv import EtagMismatch, MemoryAzureCsv
from app.pending import PendingStore, ExpiredPending
from app.propose import commit_pending

def test_etag_mismatch_does_not_write(tmp_path: Path):
    azure = MemoryAzureCsv("Email,Name\na@hku.hk,Old\n", etag="1")
    store = PendingStore(tmp_path / "p.sqlite")
    store.save({
        "etag": "1",
        "map": {"key_grist": "Email", "key_csv": "Email", "columns": [["Email", "Email"], ["Name", "Name"]]},
        "proposed_csv": "Email,Name\na@hku.hk,New\n",
        "sha256": "x",
        "author_email": "m@hku.hk",
        "expires_at": time.time() + 60,
        "hunks": [{"key": "a@hku.hk", "kind": "update", "changes": []}],
        "live_csv": "Email,Name\na@hku.hk,Old\n",
    })
    azure.etag = "2"
    try:
        commit_pending(store, azure, actor_email="boss@hku.hk", rejected_keys=[])
        raise AssertionError("expected EtagMismatch")
    except EtagMismatch:
        pass
    body, etag = azure.read()
    assert etag == "2"
    assert "Old" in body

def test_commit_writes_when_etag_matches(tmp_path: Path):
    azure = MemoryAzureCsv("Email,Name\na@hku.hk,Old\n", etag="1")
    store = PendingStore(tmp_path / "p.sqlite")
    store.save({
        "etag": "1",
        "map": {"key_grist": "Email", "key_csv": "Email", "columns": [["Email", "Email"], ["Name", "Name"]]},
        "proposed_csv": "Email,Name\na@hku.hk,New\n",
        "sha256": "x",
        "author_email": "m@hku.hk",
        "expires_at": time.time() + 60,
        "hunks": [{"key": "a@hku.hk", "kind": "update", "changes": []}],
        "live_csv": "Email,Name\na@hku.hk,Old\n",
    })
    new_etag = commit_pending(store, azure, actor_email="boss@hku.hk", rejected_keys=[])
    body, etag = azure.read()
    assert "New" in body
    assert etag == new_etag
    assert store.get() is None
