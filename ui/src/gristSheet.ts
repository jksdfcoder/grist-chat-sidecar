// ponytail: also copied to sidecar/static/app.js
const SKIP = new Set(["id", "manualSort"]);

export function isGristColId(name: string): boolean {
  return /^[A-Za-z_]\w{0,63}$/.test(name);
}

export function sheetColumns(rows: Record<string, unknown>[]): string[] {
  const names = new Set<string>();
  for (const row of rows) {
    for (const k of Object.keys(row || {})) {
      if (!SKIP.has(k)) names.add(k);
    }
  }
  return [...names];
}

export function sheetBinds(rows: Record<string, unknown>[], keys?: string[]): Record<string, string[]> {
  const allow = keys?.length ? new Set(keys) : null;
  const out: Record<string, string[]> = {};
  for (const row of rows) {
    for (const [k, v] of Object.entries(row || {})) {
      if (SKIP.has(k) || (allow && !allow.has(k)) || v == null || String(v).trim() === "") continue;
      const s = String(v);
      const list = (out[k] ??= []);
      if (!list.includes(s)) list.push(s);
    }
  }
  return out;
}

export function tableToRows(table: Record<string, unknown>[] | Record<string, unknown[]> | null | undefined): Record<string, unknown>[] {
  if (!table) return [];
  if (Array.isArray(table)) return table;
  const n = (table.id || Object.values(table)[0] || []).length;
  const cols = Object.keys(table);
  return Array.from({ length: n }, (_, i) => {
    const row: Record<string, unknown> = {};
    for (const c of cols) row[c] = table[c]?.[i];
    return row;
  });
}

export function placeholderKeys(sql: string): string[] {
  return [...new Set([...String(sql || "").matchAll(/\{\{([A-Za-z_]\w*)\}\}/g)].map((m) => m[1]))];
}

export function sqlNoteText(sql: string): string {
  const keys = placeholderKeys(sql);
  const aliases = [...String(sql || "").matchAll(/\bAS\s+"?([A-Za-z_]\w*)"?/gi)].map((m) => m[1]);
  const out = [...new Set(aliases.filter((a) => !keys.includes(a)))];
  return `Input: ${keys.join(", ") || "-"}\nOutput: ${out.join(", ") || "-"}`;
}

export function missingColumns(have: string[], want: string[]): string[] {
  const known = new Set(have.map((c) => c.toLowerCase()));
  return want.filter((c) => isGristColId(c) && !SKIP.has(c) && !known.has(c.toLowerCase()));
}

export function remapCols(rows: Record<string, unknown>[], have: string[]): Record<string, unknown>[] {
  const map = new Map(have.map((c) => [c.toLowerCase(), c]));
  return rows.map((row) => {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(row || {})) out[map.get(k.toLowerCase()) || k] = v;
    return out;
  });
}

function tidyCell(v: unknown): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.map(tidyCell).filter(Boolean).join("; ");
  const s = String(v).trim();
  if (s.startsWith("{") && s.endsWith("}")) {
    const quoted = [...s.matchAll(/"((?:\\.|[^"\\])*)"/g)].map((m) => m[1].replace(/\\"/g, '"'));
    if (quoted.length) return quoted.join("; ");
  }
  return s;
}

function emailScore(e: string): number {
  const x = e.toLowerCase();
  if (/hkucc|connect\.hku/.test(x)) return 0;
  if (x.endsWith("@hku.hk")) return 2;
  return 1;
}

function joinUnique(a: string, b: string): string {
  return [...new Set([...a.split("; "), ...b.split("; ")].map((s) => s.trim()).filter(Boolean))].join("; ");
}

export function collapseByKeys(rows: Record<string, unknown>[], keys: string[]): Record<string, unknown>[] {
  const map = new Map<string, Record<string, unknown>>();
  for (const row of rows) {
    const cur: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(row || {})) cur[k] = tidyCell(v);
    const req = (keys.length ? keys : Object.keys(cur)).map((k) => String(cur[k] || ""));
    if (keys.length && req.some((x) => !x)) continue;
    const sig = JSON.stringify(keys.length ? req : cur);
    const prev = map.get(sig);
    if (!prev) {
      map.set(sig, cur);
      continue;
    }
    for (const [k, v] of Object.entries(cur)) {
      const a = String(prev[k] || "");
      const b = String(v || "");
      prev[k] = /email/i.test(k) ? [a, b].sort((x, y) => emailScore(y) - emailScore(x))[0] || a : joinUnique(a, b);
    }
  }
  return [...map.values()];
}

export function upsertRecords(
  rows: Record<string, unknown>[],
  mapBack?: (row: Record<string, unknown>) => Record<string, unknown> | null,
  keys?: string[],
): { require: Record<string, unknown>; fields: Record<string, unknown> }[] {
  const recs = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const fields = { ...((mapBack ? mapBack(row) : row) || row) };
    for (const k of SKIP) delete fields[k];
    for (const k of Object.keys(fields)) {
      if (!isGristColId(k)) {
        delete fields[k];
        continue;
      }
      const v = fields[k];
      if (Array.isArray(v)) {
        const first = v.find((x) => x != null && String(x).trim() !== "");
        fields[k] = first == null ? "" : String(first);
      }
    }
    const require: Record<string, unknown> = {};
    for (const k of keys || []) {
      const v = fields[k] ?? row[k];
      if (v != null && String(v).trim() !== "") require[k] = v;
    }
    if (!Object.keys(require).length) continue;
    const sig = JSON.stringify(require);
    if (seen.has(sig)) continue;
    seen.add(sig);
    recs.push({ require, fields });
  }
  return recs;
}
