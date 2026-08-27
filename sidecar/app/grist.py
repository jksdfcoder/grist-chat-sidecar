class MemoryGrist:
    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]

    def list_rows(self) -> list[dict]:
        return [dict(r) for r in self.rows]

    def upsert(self, rows, key, column_map):
        cmap = column_map or {}
        index = {(r.get(key) or "").strip().lower(): i for i, r in enumerate(self.rows)}
        for row in rows:
            mapped = {cmap.get(k, k): v for k, v in row.items()}
            k = (mapped.get(key) or "").strip().lower()
            if not k:
                continue
            if k in index:
                self.rows[index[k]] = {**self.rows[index[k]], **mapped}
            else:
                index[k] = len(self.rows)
                self.rows.append(mapped)
