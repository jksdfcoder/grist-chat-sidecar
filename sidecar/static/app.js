/* ponytail: source of truth is Ver2/ui/src/{hunks,askCard,gristSheet}.ts */
function toggleRejected(rejected, key) {
  if (rejected.has(key)) rejected.delete(key);
  else rejected.add(key);
  return rejected;
}

function commitPayload(rejected) {
  return { rejected_keys: [...rejected] };
}

function answerAskCard(kind, value) {
  return JSON.stringify({ kind, value });
}

const statusEl = document.querySelector("[data-testid=status]");
function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const text = await r.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: String(text).slice(0, 180) };
  }
  if (!r.ok) {
    setStatus(`${r.status} ${data.detail || text || "error"}`);
    throw new Error(String(r.status));
  }
  return data;
}

const chatForm = document.querySelector("[data-testid=chat-input]");
const modelEl = document.querySelector("[data-testid=model]");
const effortEl = document.querySelector("[data-testid=effort]");
const askCard = document.querySelector("[data-testid=ask-card]");
const askQuestion = document.querySelector("[data-testid=ask-question]");
const askSubmit = document.querySelector("[data-testid=ask-submit]");
const sqlPreview = document.querySelector("[data-testid=sql-preview]");
const sqlExec = document.querySelector("[data-testid=sql-exec]");
const sqlSave = document.querySelector("[data-testid=sql-save]");
const sqlText = document.querySelector("[data-testid=sql-text]");
const sqlNote = document.querySelector("[data-testid=sql-note]");
const sqlSaved = document.querySelector("[data-testid=sql-saved]");
const writeGrist = document.querySelector("[data-testid=write-grist]");
const diff = document.querySelector("[data-testid=diff]");
const commit = document.querySelector("[data-testid=commit]");
const commitOk = document.querySelector("[data-testid=commit-ok]");
const logEl = document.querySelector("[data-testid=log]");
// ponytail: chat dies with the tab; only /api/sql is durable
let history = [];
let pendingAsk = null;
let lastPreview = null;
let sheetRows = [];

function inGrist() {
  return window.parent !== window && window.grist?.ready;
}

const SKIP_COLS = new Set(["id", "manualSort"]);

function isGristColId(name) {
  return /^[A-Za-z_]\w{0,63}$/.test(name);
}

function sheetColumns(rows) {
  const names = new Set();
  for (const row of rows || []) {
    for (const k of Object.keys(row || {})) {
      if (!SKIP_COLS.has(k)) names.add(k);
    }
  }
  return [...names];
}

function sheetBinds(rows) {
  const out = {};
  for (const row of rows || sheetRows) {
    for (const [k, v] of Object.entries(row || {})) {
      if (SKIP_COLS.has(k) || v == null || String(v).trim() === "") continue;
      const s = String(v);
      const list = (out[k] ??= []);
      if (!list.includes(s)) list.push(s);
    }
  }
  return out;
}

function placeholderKeys(sql) {
  return [...new Set([...(String(sql || "").matchAll(/\{\{([A-Za-z_]\w*)\}\}/g) || [])].map((m) => m[1]))];
}

function missingColumns(have, want) {
  const known = new Set((have || []).map((c) => String(c).toLowerCase()));
  return want.filter((c) => isGristColId(c) && !SKIP_COLS.has(c) && !known.has(c.toLowerCase()));
}

function remapCols(rows, have) {
  const map = new Map((have || []).map((c) => [c.toLowerCase(), c]));
  return (rows || []).map((row) => {
    const out = {};
    for (const [k, v] of Object.entries(row || {})) out[map.get(k.toLowerCase()) || k] = v;
    return out;
  });
}

function upsertRecords(rows, mapBack, keys) {
  const recs = [];
  const seen = new Set();
  for (const row of rows) {
    const fields = { ...((mapBack ? mapBack(row) : row) || row) };
    for (const k of SKIP_COLS) delete fields[k];
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
    const require = {};
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

if (inGrist()) {
  grist.ready({ requiredAccess: "full" });
  grist.onRecords((records) => {
    sheetRows = records || [];
  });
}

function saveHistory() {
  if (history.length > 30) history = history.slice(-30);
  if (logEl) {
    logEl.textContent = history
      .map((m) => `${m.role}: ${m.content || (m.tool_calls ? "[ask]" : "")}`)
      .join("\n");
  }
}

function showProposed(preview) {
  if (!preview?.sql) return;
  lastPreview = { sql: preview.sql, db: preview.db || "hub", rows: [] };
  if (sqlText) sqlText.textContent = `[${lastPreview.db}] ${lastPreview.sql}`;
  if (sqlNote && preview.note) sqlNote.value = preview.note;
  if (sqlSave) sqlSave.hidden = false;
  if (sqlExec) sqlExec.hidden = false;
  setStatus("sql ready — exec yourself");
}

async function loadSavedSql() {
  if (!sqlSaved) return;
  const r = await fetch("/api/sql");
  if (!r.ok) return;
  const items = await r.json();
  sqlSaved.replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = `${item.note} [${item.db}] `;
    const pre = document.createElement("pre");
    pre.textContent = item.sql;
    li.append(pre);
    sqlSaved.append(li);
  }
}

function chatBody(extra) {
  return {
    model: modelEl?.value || "",
    effort: effortEl?.value || "none",
    sheet_columns: sheetColumns(sheetRows),
    ...extra,
  };
}

async function loadModels() {
  if (!modelEl) return;
  const r = await fetch("/api/models");
  if (!r.ok) return;
  const data = await r.json();
  modelEl.replaceChildren();
  for (const m of data.models || []) {
    const o = document.createElement("option");
    o.value = m.id;
    o.textContent = m.free ? m.name : `${m.name} (付费)`;
    modelEl.append(o);
  }
  if (data.default) modelEl.value = data.default;
}
loadSavedSql();
loadModels();

if (chatForm) {
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    setStatus("sending…");
    const q = chatForm.querySelector("input")?.value || "";
    history.push({ role: "user", content: q });
    saveHistory();
    const data = await postJson("/api/chat/turn", chatBody({ messages: history }));
    const ask = data.tool_calls?.find((t) => t.name === "ask_question");
    if (askCard && ask) {
      pendingAsk = ask;
      history.push({
        role: "assistant",
        content: data.text || "",
        tool_calls: [
          {
            id: ask.id,
            type: "function",
            function: {
              name: ask.name,
              arguments: typeof ask.arguments === "string" ? ask.arguments : JSON.stringify(ask.arguments || {}),
            },
          },
        ],
      });
      saveHistory();
      const args = typeof ask.arguments === "string" ? JSON.parse(ask.arguments) : ask.arguments || {};
      if (askQuestion) {
        askQuestion.textContent = [args.question, (args.options || []).join(" / ")]
          .filter(Boolean)
          .join(" ");
      }
      askCard.hidden = false;
      setStatus("pick an answer");
      return;
    }
    if (data.text) history.push({ role: "assistant", content: data.text });
    saveHistory();
    showProposed(data.previews?.[0]);
    setStatus(data.previews?.[0]?.sql ? "sql ready — exec yourself" : data.text || JSON.stringify(data));
  });
}

if (askSubmit) {
  askSubmit.addEventListener("click", async () => {
    setStatus("answering…");
    const data = await postJson(
      "/api/chat/turn",
      chatBody({
        messages: history,
        tool_results: [{ id: pendingAsk?.id || "stub-ask", output: answerAskCard("single", "staff") }],
      }),
    );
    pendingAsk = null;
    if (data.text) history.push({ role: "assistant", content: data.text });
    saveHistory();
    showProposed(data.previews?.[0]);
    setStatus(data.previews?.[0]?.sql ? "sql ready — exec yourself" : data.text || JSON.stringify(data));
  });
}

if (sqlExec) {
  sqlExec.addEventListener("click", async () => {
    if (!lastPreview?.sql) {
      setStatus("no sql yet");
      return;
    }
    const data = await postJson("/api/sql/preview", {
      sql: lastPreview.sql,
      db: lastPreview.db || "hub",
      binds: sheetBinds(sheetRows),
    });
    lastPreview = { ...lastPreview, rows: remapCols(data.rows || [], sheetColumns(sheetRows)) };
    if (sqlPreview) sqlPreview.textContent = JSON.stringify(lastPreview.rows);
    setStatus("preview ready");
  });
}

if (sqlSave) {
  sqlSave.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!lastPreview?.sql) {
      setStatus("preview first");
      return;
    }
    await postJson("/api/sql", {
      sql: lastPreview.sql,
      db: lastPreview.db || "hub",
      note: sqlNote?.value || "",
    });
    if (sqlNote) sqlNote.value = "";
    setStatus("sql saved");
    await loadSavedSql();
  });
}

if (writeGrist) {
  writeGrist.addEventListener("click", async () => {
    const rows = remapCols(lastPreview?.rows || [], sheetColumns(sheetRows));
    if (inGrist() && grist.getTable) {
      const want = [...new Set(rows.flatMap((r) => Object.keys(r)))];
      const add = missingColumns(sheetColumns(sheetRows), want);
      if (add.length && grist.docApi?.applyUserActions) {
        const tableId = await grist.getTable().getTableId();
        await grist.docApi.applyUserActions(
          add.map((c) => ["AddVisibleColumn", tableId, c, { type: "Text", isFormula: false }]),
        );
      }
      const keys = placeholderKeys(lastPreview?.sql || "");
      const recs = upsertRecords(rows, undefined, keys);
      if (!keys.length || !recs.length) {
        setStatus("SQL must SELECT the lookup column ({{RP_no}})");
        return;
      }
      await grist.getTable().upsert(recs, { add: false, update: true, onMany: "all" });
      setStatus("wrote grist");
      return;
    }
    const recs = upsertRecords(rows, undefined, placeholderKeys(lastPreview?.sql || ""));
    const key = Object.keys(recs[0]?.require || {})[0] || "Email";
    await postJson("/api/grist/write", { rows, key });
    setStatus("wrote grist");
  });
}

if (diff) {
  postJson("/api/submit/prepare", {}).then((data) => {
    diff.textContent = JSON.stringify(data.hunks ?? []);
  });
}

if (commit) {
  commit.addEventListener("click", async () => {
    const r = await fetch("/api/submit/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(commitPayload(new Set())),
    });
    if (r.ok && commitOk) commitOk.hidden = false;
  });
}
