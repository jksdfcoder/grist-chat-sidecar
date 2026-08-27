import json
import sqlite3
import time


class ExpiredPending(Exception):
    pass


class PendingStore:
    def __init__(self, path):
        # ponytail: one connection; FastAPI hops threads. WAL/pool if workers > 1.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS pending(id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT)"
        )
        # ponytail: recipes share this file; split tables if pending and catalog contend
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS saved_sql("
            "id INTEGER PRIMARY KEY, sql TEXT NOT NULL, note TEXT NOT NULL, "
            "db TEXT NOT NULL, author TEXT NOT NULL, created REAL NOT NULL)"
        )
        # ponytail: templates+history in this sqlite; files on disk if CSVs get huge
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS azure_templates("
            "id INTEGER PRIMARY KEY, name TEXT NOT NULL, account TEXT NOT NULL, "
            "container TEXT NOT NULL, path TEXT NOT NULL, account_key TEXT NOT NULL, "
            "author TEXT NOT NULL, created REAL NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS upload_history("
            "id INTEGER PRIMARY KEY, created REAL NOT NULL, author TEXT NOT NULL, "
            "kind TEXT NOT NULL, dest TEXT NOT NULL, account TEXT NOT NULL, "
            "container TEXT NOT NULL, path TEXT NOT NULL, etag TEXT NOT NULL, "
            "body TEXT NOT NULL, columns TEXT NOT NULL, note TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS upload_requests("
            "id INTEGER PRIMARY KEY, created REAL NOT NULL, author TEXT NOT NULL, "
            "status TEXT NOT NULL, dest TEXT NOT NULL, template_id INTEGER, "
            "account TEXT NOT NULL, container TEXT NOT NULL, path TEXT NOT NULL, "
            "account_key TEXT NOT NULL, columns TEXT NOT NULL, key_grist TEXT NOT NULL, "
            "key_csv TEXT NOT NULL, rows TEXT NOT NULL, note TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS openai_endpoint("
            "id INTEGER PRIMARY KEY CHECK (id = 1), base_url TEXT NOT NULL, api_key TEXT NOT NULL)"
        )
        self._db.commit()

    def save(self, record: dict) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO pending(id, json) VALUES (1, ?)",
            (json.dumps(record),),
        )
        self._db.commit()

    def get(self) -> dict | None:
        row = self._db.execute("SELECT json FROM pending WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else None

    def clear(self) -> None:
        self._db.execute("DELETE FROM pending")
        self._db.commit()

    def save_sql(self, *, sql: str, note: str, db: str, author: str) -> int:
        cur = self._db.execute(
            "INSERT INTO saved_sql(sql, note, db, author, created) VALUES (?,?,?,?,?)",
            (sql, note, db, author, time.time()),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def list_sql(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, sql, note, db, author, created FROM saved_sql ORDER BY created DESC, id DESC"
        ).fetchall()
        return [
            {"id": r[0], "sql": r[1], "note": r[2], "db": r[3], "author": r[4], "created": r[5]}
            for r in rows
        ]

    def delete_sql(self, sql_id: int) -> bool:
        cur = self._db.execute("DELETE FROM saved_sql WHERE id = ?", (sql_id,))
        self._db.commit()
        return cur.rowcount > 0

    def rename_sql(self, sql_id: int, note: str) -> bool:
        cur = self._db.execute("UPDATE saved_sql SET note = ? WHERE id = ?", (note, sql_id))
        self._db.commit()
        return cur.rowcount > 0

    def save_template(self, *, name: str, account: str, container: str, path: str, account_key: str, author: str) -> int:
        cur = self._db.execute(
            "INSERT INTO azure_templates(name, account, container, path, account_key, author, created) "
            "VALUES (?,?,?,?,?,?,?)",
            (name, account, container, path, account_key, author, time.time()),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def list_templates(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, name, account, container, path, author, created FROM azure_templates "
            "ORDER BY created DESC, id DESC"
        ).fetchall()
        return [
            {"id": r[0], "name": r[1], "account": r[2], "container": r[3], "path": r[4], "author": r[5], "created": r[6]}
            for r in rows
        ]

    def get_template(self, tid: int) -> dict | None:
        r = self._db.execute(
            "SELECT id, name, account, container, path, account_key, author, created FROM azure_templates WHERE id = ?",
            (tid,),
        ).fetchone()
        if not r:
            return None
        return {
            "id": r[0],
            "name": r[1],
            "account": r[2],
            "container": r[3],
            "path": r[4],
            "account_key": r[5],
            "author": r[6],
            "created": r[7],
        }

    def rename_template(self, tid: int, name: str) -> bool:
        cur = self._db.execute("UPDATE azure_templates SET name = ? WHERE id = ?", (name, tid))
        self._db.commit()
        return cur.rowcount > 0

    def delete_template(self, tid: int) -> bool:
        cur = self._db.execute("DELETE FROM azure_templates WHERE id = ?", (tid,))
        self._db.commit()
        return cur.rowcount > 0

    def add_upload_hist(self, *, author: str, kind: str, dest: str, account: str, container: str, path: str, etag: str, body: str, columns: list[str], note: str) -> int:
        cur = self._db.execute(
            "INSERT INTO upload_history(created, author, kind, dest, account, container, path, etag, body, columns, note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), author, kind, dest, account, container, path, etag, body, json.dumps(columns), note),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def list_upload_hist(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, created, author, kind, dest, account, container, path, etag, length(body), columns, note "
            "FROM upload_history ORDER BY created DESC, id DESC"
        ).fetchall()
        return [
            {
                "id": r[0],
                "created": r[1],
                "author": r[2],
                "kind": r[3],
                "dest": r[4],
                "account": r[5],
                "container": r[6],
                "path": r[7],
                "etag": r[8],
                "bytes": r[9],
                "columns": json.loads(r[10] or "[]"),
                "note": r[11],
            }
            for r in rows
        ]

    def get_upload_hist(self, hid: int) -> dict | None:
        r = self._db.execute(
            "SELECT id, created, author, kind, dest, account, container, path, etag, body, columns, note "
            "FROM upload_history WHERE id = ?",
            (hid,),
        ).fetchone()
        if not r:
            return None
        return {
            "id": r[0],
            "created": r[1],
            "author": r[2],
            "kind": r[3],
            "dest": r[4],
            "account": r[5],
            "container": r[6],
            "path": r[7],
            "etag": r[8],
            "body": r[9],
            "columns": json.loads(r[10] or "[]"),
            "note": r[11],
        }

    def add_upload_request(self, rec: dict) -> int:
        cur = self._db.execute(
            "INSERT INTO upload_requests(created, author, status, dest, template_id, account, container, path, "
            "account_key, columns, key_grist, key_csv, rows, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                rec["author"],
                rec.get("status") or "pending",
                rec["dest"],
                rec.get("template_id"),
                rec["account"],
                rec["container"],
                rec["path"],
                rec.get("account_key") or "",
                json.dumps(rec["columns"]),
                rec["key_grist"],
                rec["key_csv"],
                json.dumps(rec["rows"]),
                rec.get("note") or "",
            ),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def list_upload_requests(self, *, author: str | None = None, pending_only: bool = True) -> list[dict]:
        q = "SELECT id, created, author, status, dest, template_id, account, container, path, columns, key_grist, key_csv, note FROM upload_requests"
        args: list = []
        where = []
        if author:
            where.append("author = ?")
            args.append(author)
        if pending_only:
            where.append("status = 'pending'")
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY created DESC, id DESC"
        rows = self._db.execute(q, args).fetchall()
        return [
            {
                "id": r[0],
                "created": r[1],
                "author": r[2],
                "status": r[3],
                "dest": r[4],
                "template_id": r[5],
                "account": r[6],
                "container": r[7],
                "path": r[8],
                "columns": json.loads(r[9] or "[]"),
                "key_grist": r[10],
                "key_csv": r[11],
                "note": r[12],
            }
            for r in rows
        ]

    def get_upload_request(self, rid: int) -> dict | None:
        r = self._db.execute(
            "SELECT id, created, author, status, dest, template_id, account, container, path, account_key, "
            "columns, key_grist, key_csv, rows, note FROM upload_requests WHERE id = ?",
            (rid,),
        ).fetchone()
        if not r:
            return None
        return {
            "id": r[0],
            "created": r[1],
            "author": r[2],
            "status": r[3],
            "dest": r[4],
            "template_id": r[5],
            "account": r[6],
            "container": r[7],
            "path": r[8],
            "account_key": r[9],
            "columns": json.loads(r[10] or "[]"),
            "key_grist": r[11],
            "key_csv": r[12],
            "rows": json.loads(r[13] or "[]"),
            "note": r[14],
        }

    def mark_request(self, rid: int, status: str) -> None:
        self._db.execute("UPDATE upload_requests SET status = ? WHERE id = ?", (status, rid))
        self._db.commit()

    def get_openai(self) -> dict | None:
        row = self._db.execute("SELECT base_url, api_key FROM openai_endpoint WHERE id = 1").fetchone()
        return {"base_url": row[0], "api_key": row[1]} if row else None

    def set_openai(self, base_url: str, api_key: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO openai_endpoint(id, base_url, api_key) VALUES (1, ?, ?)",
            (base_url, api_key),
        )
        self._db.commit()
