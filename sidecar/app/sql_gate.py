import re

import sqlglot
from sqlglot import exp

_WRITES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Into)
# ponytail: Cursor-style denylist (top1_sql_query + agent hang rules); planner cost if this lags real scans
_FN = frozenset({
    "pg_sleep", "pg_read_file", "pg_write_file", "pg_ls_dir", "pg_stat_file",
    "lo_export", "lo_import", "dblink", "dblink_exec", "dblink_connect",
    "set_config", "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
})
_FAT = frozenset({
    "metadata", "wos_publications", "wos_publication_authors",
    "scopus_abstract", "scopus_author_publications",
})
_SECRET = frozenset({"pg_authid", "pg_shadow"})
_PLACE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
# ponytail: model often writes = '{{RP_no}}'; multiple binds must become IN (...)
_BIND = re.compile(
    r"(?<![<>!])(?P<op>=\s*)?(?:"
    r"(?P<q>['\"])\{\{(?P<key>[A-Za-z_][A-Za-z0-9_]*)\}\}(?P=q)"
    r"|"
    r"\{\{(?P<key2>[A-Za-z_][A-Za-z0-9_]*)\}\}"
    r")"
)


_LOOKUP = re.compile(
    r"([A-Za-z_][\w.]*)\s*(?:=|IN)\s*(?:\(\s*)?(?:['\"]?){{([A-Za-z_]\w*)}}",
    re.I,
)
# ponytail: leading % forces seq scan; prefix LIKE 'WOS:%' is fine
_LEAD_LIKE = re.compile(r"(?i)(?:I?LIKE|SIMILAR\s+TO)\s+'%")


def sql_for_gate(sql: str) -> str:
    return _PLACE.sub("NULL", sql)


def bind_placeholders(sql: str, binds: dict | None) -> str:
    binds = binds or {}

    def repl(m):
        key = m.group("key") or m.group("key2")
        if key not in binds:
            raise ValueError(f"unbound {{{{{key}}}}}")
        vals = binds[key]
        if not isinstance(vals, list):
            vals = [] if vals is None else [vals]
        parts = ["'" + str(v).replace("'", "''") + "'" for v in vals if v is not None and str(v).strip() != ""]
        lit = ", ".join(parts) if parts else "NULL"
        op = m.group("op")
        if op and len(parts) != 1:
            return f"IN ({lit})"
        if op:
            return f"{op}{lit}"
        return lit

    return _BIND.sub(repl, sql)


# ponytail: inject lookup col into SELECT so Grist upsert can match; skip a real SQL rewriter until queries have joins
def select_lookup_cols(sql: str) -> str:
    adds = []
    for col, key in _LOOKUP.findall(sql or ""):
        if re.search(rf'\bAS\s+"{re.escape(key)}"|\bAS\s+{re.escape(key)}\b', sql or "", re.I):
            continue
        piece = f'{col} AS "{key}"'
        if piece not in adds:
            adds.append(piece)
    if not adds:
        return sql
    return re.sub(r"(?is)^(\s*SELECT\s+)", r"\1" + ", ".join(adds) + ", ", sql, count=1)


def _pattern_lit(node):
    pat = node.args.get("expression") if node else None
    if isinstance(pat, exp.Literal) and pat.args.get("is_string"):
        return str(pat.this)
    return None


def _has_key_filter(expr) -> bool:
    if expr.find(exp.EQ) or expr.find(exp.In):
        return True
    for node in expr.find_all(exp.Like, exp.ILike):
        lit = _pattern_lit(node)
        if lit is not None and not lit.startswith("%"):
            return True
    return False


def _reject(expr) -> None:
    if any(w.args.get("recursive") for w in expr.find_all(exp.With)):
        raise ValueError("path blocked: WITH RECURSIVE is not allowed")
    if expr.find(exp.Lock):
        raise ValueError("path blocked: FOR UPDATE/SHARE is not allowed")
    if expr.find(exp.Offset):
        raise ValueError("path blocked: OFFSET is not allowed; tighten the WHERE")
    if expr.find(exp.GenerateSeries):
        raise ValueError("path blocked: generate_series is not allowed")
    for fn in expr.find_all(exp.Anonymous):
        name = str(fn.this or "").lower().rsplit(".", 1)[-1]
        if name in _FN:
            raise ValueError(f"path blocked: {name} is not allowed")
    for node in expr.find_all(exp.Like, exp.ILike, exp.SimilarTo):
        lit = _pattern_lit(node)
        if lit is None or lit.startswith("%"):
            raise ValueError("leading-wildcard LIKE is a full table scan; filter by an id column")
    names = {t.name.lower() for t in expr.find_all(exp.Table) if t.name}
    if names & _SECRET:
        raise ValueError("path blocked: catalog table is not allowed")
    if names & _FAT and not _has_key_filter(expr):
        raise ValueError(
            "path blocked: table needs an equality or prefix LIKE on an id column; do not scan the whole table"
        )


def gate_select(sql: str, limit: int = 20) -> str:
    if _LEAD_LIKE.search(sql or ""):
        raise ValueError("leading-wildcard LIKE is a full table scan; filter by an id column")
    try:
        trees = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.ParseError as e:
        raise ValueError("invalid SQL") from e
    if len(trees) != 1 or trees[0] is None:
        raise ValueError("expected a single SELECT")
    expr = trees[0]
    # ponytail: sqlglot types SELECT INTO and DML CTEs as Select; walk the tree
    if expr.find(*_WRITES):
        raise ValueError("SELECT only")
    _reject(expr)
    if isinstance(expr, exp.With):
        expr = expr.this
    if not isinstance(expr, (exp.Select, exp.Union)):
        raise ValueError("SELECT only")
    return expr.limit(min(limit, 20)).sql(dialect="postgres")
