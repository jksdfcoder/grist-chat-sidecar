<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { collapseByKeys, missingColumns, placeholderKeys, remapCols, sheetBinds, sheetColumns, tableToRows, upsertRecords } from "@sheet";
import mascot from "./assets/octopus-astronaut.png";
import UploadModal from "./UploadModal.vue";

type Preview = {
  sql: string;
  db: string;
  note?: string;
  rows: Record<string, unknown>[];
  err?: string;
  armed?: boolean;
  gen?: number;
  saving?: boolean;
  savedId?: number;
  ran?: boolean;
};

type ToolUse = { name: string; arguments?: unknown; output?: string };

type ChatMsg = {
  role: string;
  content?: string;
  reasoning?: string;
  tool_calls?: unknown[];
  previews?: Preview[];
  tools?: ToolUse[];
};

type Model = { id: string; name: string; free: boolean; via?: string };
type SavedSql = { id: number; sql: string; db: string; note: string; created?: number };

const status = ref("");
const logText = ref("");
const draft = ref("");
const busy = ref(false);
let chatAbort: AbortController | null = null;
const history = ref<ChatMsg[]>([]);
const pendingAsk = ref<{ id: string; question: string; options: string[] } | null>(null);
const histPreview = ref<Preview | null>(null);
const savedSql = ref<SavedSql[]>([]);
const sqlOpen = ref(false);
const histErr = ref("");
const histWriteArmed = ref(false);
let histGen = 0;
const plusOnes = ref<number[]>([]);
let plusSeq = 0;
const deleteArmed = ref<number | null>(null);
const sheetRows = ref<Record<string, unknown>[]>([]);
const extraCols = ref<string[]>([]);
const models = ref<Model[]>([]);
const model = ref("");
const effort = ref("none");
const role = ref("");
const openaiConfigured = ref(false);
const openaiHost = ref("");
const openaiBase = ref("");
const openaiOpen = ref(false);
const openaiUrl = ref("");
const openaiKey = ref("");
const openaiErr = ref("");
const openaiBusy = ref(false);
const uploadOpen = ref(false);
const lastModel = ref("");
const LOCAL_CFG = "__local_cfg__";

const effortItems = [
  { label: "Off", value: "none" },
  { label: "Low", value: "low" },
  { label: "Medium", value: "medium" },
  { label: "High", value: "high" },
  { label: "Max", value: "xhigh" },
];

const modelItems = computed(() => {
  const row = (m: Model) => ({
    label: m.via === "openai" ? m.name : m.free ? m.name : `${m.name} (paid)`,
    value: m.id,
  });
  const local = models.value.filter((m) => m.via === "openai").map(row);
  const remote = models.value.filter((m) => m.via !== "openai").map(row);
  const localGroup = local.length
    ? [{ type: "label" as const, label: "Local" }, ...local]
    : [
        { type: "label" as const, label: "Local" },
        {
          label: openaiHost.value ? `${openaiHost.value} 未连接` : "配置连接",
          value: LOCAL_CFG,
          onSelect: (e: Event) => {
            e.preventDefault();
            openaiOpen.value = true;
          },
        },
      ];
  const remoteGroup = remote.length ? [{ type: "label" as const, label: "OpenRouter" }, ...remote] : [];
  if (localGroup.length && remoteGroup.length) {
    return [[...localGroup, { type: "separator" as const }], remoteGroup];
  }
  if (localGroup.length) return localGroup;
  return remote;
});

const chatMessages = computed(() =>
  history.value.flatMap((m, i) => {
    if (m.content === "SQL ready.") return [];
    const text = (m.content || "").trim();
    const reasoning = (m.reasoning || "").trim();
    const previews = m.previews || [];
    const tools = m.tools || [];
    const asked = (m.tool_calls as unknown[] | undefined)?.length;
    const live = busy.value && i === history.value.length - 1;
    if (m.role !== "assistant") {
      if (!text || asked) return [];
      return [{ id: String(i), role: "user" as const, parts: [{ type: "text" as const, text }] }];
    }
    if (asked && !reasoning && !previews.length && !tools.length && !live) return [];
    if (!asked && !text && !reasoning && !previews.length && !tools.length && !live) return [];
    return [
      {
        id: String(i),
        role: "assistant" as const,
        tools,
        previews,
        parts: [
          ...(reasoning || live ? [{ type: "reasoning" as const, text: reasoning }] : []),
          ...(tools.length ? [{ type: "tools" as const }] : []),
          ...(!asked && text ? [{ type: "text" as const, text }] : []),
          ...previews.map((p) => ({ type: "sql" as const, text: p.sql })),
        ],
      },
    ];
  }),
);

const actionUi = { actions: "opacity-100 static mt-0.5" };
const userUi = { ...actionUi, root: "min-w-0", content: "min-w-0 max-w-full overflow-hidden ring-2 ring-primary" };
const assistantUi = {
  ...actionUi,
  leadingAvatarSize: "sm",
  leading: "mt-1.5",
  root: "min-w-0",
  content: "min-w-0 max-w-full overflow-hidden rounded-md px-2 py-1.5 ring-2 ring-primary",
};
const mascotAvatar = { src: mascot, alt: "", ui: { root: "bg-transparent", image: "dark:invert" } };
const sqlToolUi = {
  root: "min-w-0 overflow-hidden rounded-md ring-0",
  body: "max-h-52 overflow-auto border-t-2 border-primary p-2 text-default",
};
const promptStatus = computed(() => {
  if (!busy.value) return "ready";
  return chatMessages.value.at(-1)?.role === "assistant" ? "streaming" : "submitted";
});
const canSend = computed(() => Boolean(draft.value.trim()) && !busy.value);
const histRows = computed(() => histPreview.value?.rows || []);
const hasSql = computed(() => history.value.some((m) => m.previews?.some((p) => p.sql)));
const hasHistSql = computed(() => Boolean(histPreview.value?.sql));
const hasHistRows = computed(() => histRows.value.length > 0);
const savedByCreated = computed(() =>
  [...savedSql.value].sort((a, b) => (b.created || 0) - (a.created || 0) || b.id - a.id),
);
const slideUi = {
  content: "w-full max-w-full overflow-hidden",
  body: "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-0",
};
const paletteUi = {
  root: "flex h-full min-h-0 min-w-0 flex-col overflow-hidden",
  content: "flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
  prompt: "min-w-0 shrink-0 p-2 pt-3",
};

function createdAt(t?: number) {
  return t ? new Date(t * 1000).toLocaleString() : "";
}

function inGrist() {
  return window.parent !== window && Boolean(window.grist?.ready);
}

function setStatus(text: string) {
  status.value = text;
}

function bumpDebug(event: string) {
  const last = history.value.flatMap((m) => m.previews || []).at(-1);
  void fetch("/api/chat/debug", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event,
      status: status.value,
      cols: sheetColumns(sheetRows.value),
      ph: placeholderKeys(last?.sql || ""),
      n: last?.rows?.length || 0,
    }),
  }).catch(() => {});
}

function saveHistory() {
  if (history.value.length > 30) history.value = history.value.slice(-30);
  logText.value = history.value
    .map((m) => `${m.role}: ${m.content || (m.tool_calls ? "[ask]" : "")}`)
    .join("\n");
}

function isAbort(e: unknown) {
  return e instanceof Error && e.name === "AbortError";
}

function startBusy() {
  chatAbort = new AbortController();
  busy.value = true;
}

function stopTurn() {
  chatAbort?.abort();
}

async function postJson(url: string, body: unknown) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const text = await r.text();
  let data: { detail?: string; id?: number; rows?: Record<string, unknown>[] } = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text.slice(0, 180) };
  }
  if (!r.ok) {
    setStatus(`${r.status} ${data.detail || text || "error"}`);
    throw new Error(String(r.status));
  }
  return data;
}

type TurnData = {
  type?: string;
  text?: string;
  reasoning?: string;
  tool_calls?: { id: string; name: string; arguments: unknown }[];
  previews?: { sql?: string; db?: string; note?: string }[];
  tools?: ToolUse[];
};

function isLive(id: string) {
  return busy.value && Number(id) === history.value.length - 1;
}

function bumpHistory() {
  history.value = history.value.slice();
}

function applyTurnEvent(live: ChatMsg, ev: TurnData & { index?: number; name?: string; arguments?: unknown; output?: string; text?: string }) {
  if (ev.type === "reasoning" && ev.text) {
    live.reasoning = ev.text;
    bumpHistory();
    return;
  }
  if (ev.type === "tool" && ev.name) {
    const tools = live.tools || [];
    const item: ToolUse = { name: ev.name, arguments: ev.arguments, output: ev.output || "" };
    if (typeof ev.index === "number") {
      while (tools.length <= ev.index) tools.push({ name: "", output: "" });
      tools[ev.index] = item;
    } else tools.push(item);
    live.tools = tools.slice();
    bumpHistory();
  }
}

function isTurnPayload(ev: TurnData) {
  return Boolean(ev.type === "done" || ev.tools || ev.previews || ev.tool_calls || ev.text || ev.reasoning);
}

async function postTurn(body: unknown, live: ChatMsg): Promise<TurnData> {
  const r = await fetch("/api/chat/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
    body: JSON.stringify(body ?? {}),
    signal: chatAbort?.signal,
  });
  const ctype = r.headers.get("content-type") || "";
  if (!r.ok) {
    const text = await r.text();
    let detail = text.slice(0, 180);
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail || detail;
    } catch {
      /* plain */
    }
    setStatus(`${r.status} ${detail || "error"}`);
    throw new Error(String(r.status));
  }
  if (!ctype.includes("ndjson") || !r.body) {
    const text = await r.text();
    return text ? JSON.parse(text) : {};
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let done: TurnData = {};
  const onLine = (line: string) => {
    const ev = JSON.parse(line) as TurnData & { index?: number; name?: string; arguments?: unknown; output?: string };
    if (isTurnPayload(ev) && ev.type !== "tool" && ev.type !== "reasoning") done = ev;
    else applyTurnEvent(live, ev);
  };
  for (;;) {
    const { value, done: eof } = await reader.read();
    if (value) {
      buf += dec.decode(value, { stream: !eof });
      const parts = buf.split("\n");
      buf = parts.pop() || "";
      for (const line of parts) if (line.trim()) onLine(line);
    }
    if (eof) break;
  }
  if (buf.trim()) onLine(buf);
  return done;
}

function chatBody(extra: Record<string, unknown>) {
  return {
    model: model.value || "",
    effort: effort.value || "none",
    sheet_columns: sheetColumns(sheetRows.value),
    ...extra,
  };
}

function wireMessages() {
  return history.value.map(({ role, content, reasoning, tool_calls }) => ({
    role,
    content,
    ...(reasoning ? { reasoning } : {}),
    ...(tool_calls ? { tool_calls } : {}),
  }));
}

function msgTools(message: { id?: string; tools?: ToolUse[] }): ToolUse[] {
  return message.tools || history.value[Number(message.id)]?.tools || [];
}

function toolArgs(t: ToolUse): Record<string, unknown> {
  const a = t.arguments;
  if (typeof a === "string") {
    try {
      return JSON.parse(a || "{}") as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return a && typeof a === "object" ? (a as Record<string, unknown>) : {};
}

function toolSuffix(t: ToolUse) {
  const a = toolArgs(t);
  if (t.name === "list_tables") return String(a.db || "hub");
  if (t.name === "describe_table") return String(a.table || "");
  if (t.name === "preview_sql") {
    const sql = String(a.sql || "").replace(/\s+/g, " ").trim();
    return sql.length > 48 ? `${sql.slice(0, 47)}…` : sql;
  }
  return "";
}

function toolBody(t: ToolUse) {
  const a = toolArgs(t);
  const sql = typeof a.sql === "string" ? a.sql : "";
  const cmd =
    t.name === "list_tables"
      ? `list_tables --db ${a.db || "hub"}`
      : t.name === "describe_table"
        ? `describe_table ${a.table || ""} --db ${a.db || "hub"}`
        : t.name === "preview_sql"
          ? `preview_sql --db ${a.db || "hub"}`
          : t.name;
  return [cmd, sql, t.output].filter(Boolean).join("\n");
}

function isSaved(p: Preview) {
  return Boolean(p.savedId && savedSql.value.some((s) => s.id === p.savedId));
}

async function savePreview(p: Preview) {
  if (p.saving || isSaved(p)) return;
  p.saving = true;
  try {
    const data = await postJson("/api/sql", {
      sql: p.sql,
      db: p.db || "hub",
      note: (p.note || "").trim() || "query",
    });
    await loadSavedSql();
    p.savedId = typeof data.id === "number" ? data.id : undefined;
    const id = ++plusSeq;
    plusOnes.value.push(id);
    setTimeout(() => {
      plusOnes.value = plusOnes.value.filter((x) => x !== id);
    }, 900);
  } catch {
    /* status already set */
  } finally {
    p.saving = false;
  }
}

async function loadSavedSql() {
  const r = await fetch("/api/sql");
  if (!r.ok) return;
  savedSql.value = await r.json();
}

async function runSaved(item: { sql: string; db: string; note: string }) {
  deleteArmed.value = null;
  histPreview.value = { sql: item.sql, db: item.db || "hub", note: item.note, rows: [] };
  histErr.value = "";
  histWriteArmed.value = false;
  sqlOpen.value = true;
  await runPreview("hist");
}

async function deleteSaved(id: number) {
  const r = await fetch(`/api/sql/${id}`, { method: "DELETE" });
  if (!r.ok) {
    setStatus(`Delete failed ${r.status}`);
    return;
  }
  deleteArmed.value = null;
  await loadSavedSql();
}

async function renameSaved(id: number, raw: string) {
  const note = raw.trim().slice(0, 200);
  const cur = savedSql.value.find((s) => s.id === id);
  if (!note || !cur || note === cur.note) return;
  const r = await fetch(`/api/sql/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  if (!r.ok) {
    setStatus(`Rename failed ${r.status}`);
    return;
  }
  cur.note = note;
}

function onDeleteClick(id: number) {
  if (deleteArmed.value !== id) {
    deleteArmed.value = id;
    return;
  }
  void deleteSaved(id);
}

async function loadModels() {
  const r = await fetch("/api/models");
  if (!r.ok) return;
  const data = await r.json();
  models.value = data.models || [];
  openaiConfigured.value = Boolean(data.openai);
  openaiHost.value = data.openai_host || "";
  openaiBase.value = data.openai_base_url || "";
  if (data.role) role.value = data.role;
  const ids = new Set(models.value.map((m) => m.id));
  const localId = models.value.find((m) => m.via === "openai")?.id;
  if (!model.value || !ids.has(model.value) || model.value === LOCAL_CFG) model.value = localId || data.default || "";
  lastModel.value = model.value;
}

watch(model, (id) => {
  if (id !== LOCAL_CFG) {
    lastModel.value = id;
    return;
  }
  openaiOpen.value = true;
  void nextTick(() => {
    model.value = lastModel.value;
  });
});

watch(openaiOpen, (v) => {
  if (!v) return;
  openaiErr.value = "";
  openaiKey.value = "";
  if (!openaiUrl.value) openaiUrl.value = openaiBase.value || "http://127.0.0.1:25890/v1";
});

function openOpenai() {
  openaiOpen.value = true;
}

async function saveOpenai() {
  openaiErr.value = "";
  openaiBusy.value = true;
  try {
    const r = await fetch("/api/models/openai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: openaiUrl.value, api_key: openaiKey.value }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "connect failed");
    models.value = data.models || [];
    openaiConfigured.value = true;
    openaiHost.value = data.openai_host || "";
    openaiBase.value = data.openai_base_url || openaiUrl.value;
    const localId = models.value.find((m) => m.via === "openai")?.id;
    if (localId) model.value = localId;
    openaiOpen.value = false;
    openaiKey.value = "";
  } catch (e) {
    openaiErr.value = e instanceof Error ? e.message : "connect failed";
  } finally {
    openaiBusy.value = false;
  }
}

async function finishTurn(live: ChatMsg, data: TurnData) {
  const tools = data.tools?.length ? data.tools : live.tools || [];
  const ask = data.tool_calls?.find((t) => t.name === "ask_question");
  live.tools = tools;
  live.reasoning = data.reasoning || live.reasoning || "";
  live.content = data.text || "";
  if (ask) {
    live.tool_calls = [
      {
        id: ask.id,
        type: "function",
        function: {
          name: ask.name,
          arguments: typeof ask.arguments === "string" ? ask.arguments : JSON.stringify(ask.arguments || {}),
        },
      },
    ];
    saveHistory();
    bumpHistory();
    const args = typeof ask.arguments === "string" ? JSON.parse(ask.arguments) : ask.arguments || {};
    pendingAsk.value = {
      id: ask.id,
      question: args.question || "",
      options: args.options || [],
    };
    status.value = "";
    return;
  }
  const previews: Preview[] = (data.previews || [])
    .filter((p) => p.sql)
    .map((p) => ({ sql: p.sql || "", db: p.db || "hub", note: p.note, rows: [] }));
  live.previews = previews;
  bumpHistory();
  saveHistory();
  for (const p of previews) await runPreviewOn(p);
  if (!previews.length && !live.content && !live.reasoning && !tools.length) setStatus("No SQL returned.");
}

async function runTurn() {
  startBusy();
  status.value = "";
  const msgs = wireMessages();
  history.value.push({ role: "assistant", content: "", reasoning: "", tools: [], previews: [] });
  const live = history.value[history.value.length - 1];
  try {
    const data = await postTurn(chatBody({ messages: msgs }), live);
    await finishTurn(live, data);
  } catch (e) {
    if (!live.tools?.length && !live.reasoning && history.value.at(-1) === live) history.value.pop();
    if (!isAbort(e)) setStatus(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

function revertAt(i: number) {
  if (busy.value || i < 0) return;
  draft.value = history.value[i]?.content || "";
  history.value = history.value.slice(0, i);
  pendingAsk.value = null;
  saveHistory();
  status.value = "";
}

async function rerunAt(i: number) {
  if (busy.value || i < 0) return;
  const u =
    history.value[i]?.role === "user"
      ? i
      : history.value.slice(0, i + 1).findLastIndex((m) => m.role === "user" && (m.content || "").trim() && !m.tool_calls);
  if (u < 0) return;
  history.value = history.value.slice(0, u + 1);
  pendingAsk.value = null;
  saveHistory();
  await runTurn();
}

function copyMsg(message: { parts?: { type?: string; text?: string }[] }) {
  void navigator.clipboard.writeText(
    (message.parts || []).filter((p) => p.type !== "reasoning").map((p) => p.text || "").join(""),
  );
}

async function onSubmit() {
  if (pendingAsk.value) {
    await answerAsk();
    return;
  }
  const q = draft.value.trim();
  if (!q || busy.value) return;
  draft.value = "";
  history.value.push({ role: "user", content: q });
  saveHistory();
  await runTurn();
}

async function answerAsk(choice?: string) {
  const value = (typeof choice === "string" ? choice : draft.value).trim();
  if (!value || busy.value || !pendingAsk.value) return;
  startBusy();
  draft.value = "";
  status.value = "";
  const msgs = wireMessages();
  history.value.push({ role: "assistant", content: "", reasoning: "", tools: [], previews: [] });
  const live = history.value[history.value.length - 1];
  try {
    const data = await postTurn(
      chatBody({
        messages: msgs,
        tool_results: [{ id: pendingAsk.value.id, output: JSON.stringify({ kind: "single", value }) }],
      }),
      live,
    );
    pendingAsk.value = null;
    await finishTurn(live, data);
  } catch (e) {
    if (!live.tools?.length && !live.reasoning && history.value.at(-1) === live) history.value.pop();
    if (!isAbort(e)) setStatus(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

async function refreshSheetRows() {
  const g = window.grist;
  if (!inGrist() || !g) return;
  try {
    if (g.fetchSelectedTable) {
      sheetRows.value = tableToRows(
        await g.fetchSelectedTable({ keepEncoded: false, format: "rows", includeColumns: "normal" }),
      );
      return;
    }
    const tableId = await g.getTable?.()?.getTableId();
    const table = tableId && g.docApi?.fetchTable ? await g.docApi.fetchTable(tableId) : null;
    if (table) sheetRows.value = tableToRows(table);
  } catch {
    /* ponytail: last onRecords snapshot if live fetch fails */
  }
}

function emptyHint(p: Preview) {
  const ph = placeholderKeys(p.sql);
  if (ph.length && !Object.keys(sheetBinds(sheetRows.value, ph)).length) {
    return `0 rows · ${p.db} · 表格没有可绑定的 ${ph.map((k) => "{{" + k + "}}").join(" ")}`;
  }
  if (!ph.length) return `0 rows · ${p.db} · SQL 没有 {{列}}，选中行未绑定`;
  return `0 rows · ${p.db}`;
}

async function runPreviewOn(p: Preview) {
  p.gen = (p.gen || 0) + 1;
  const gen = p.gen;
  busy.value = true;
  p.err = "";
  p.armed = false;
  try {
    await refreshSheetRows();
    if (p.gen !== gen) return;
    const data = await postJson("/api/sql/preview", {
      sql: p.sql,
      db: p.db || "hub",
      binds: sheetBinds(sheetRows.value, placeholderKeys(p.sql)),
    });
    if (p.gen !== gen) return;
    p.rows = collapseByKeys(remapCols(data.rows || [], sheetColumns(sheetRows.value)), placeholderKeys(p.sql));
    p.ran = true;
    p.err = p.rows.length ? "" : emptyHint(p);
    status.value = "";
    bumpHistory();
  } catch (e) {
    if (p.gen !== gen) return;
    p.ran = true;
    p.rows = [];
    p.err = isAbort(e) ? "cancelled" : status.value || (e instanceof Error ? e.message : String(e));
    status.value = "";
    bumpHistory();
  } finally {
    if (p.gen === gen) busy.value = false;
  }
}

async function runPreview(kind: "hist") {
  const gen = ++histGen;
  const live = () => gen === histGen;
  if (!histPreview.value?.sql) return;
  busy.value = true;
  await refreshSheetRows();
  if (!live()) return;
  const sql = histPreview.value.sql;
  histErr.value = "";
  histWriteArmed.value = false;
  try {
    const data = await postJson("/api/sql/preview", {
      sql,
      db: histPreview.value.db || "hub",
      binds: sheetBinds(sheetRows.value, placeholderKeys(sql)),
    });
    if (!live()) return;
    histPreview.value = {
      ...histPreview.value,
      rows: collapseByKeys(remapCols(data.rows || [], sheetColumns(sheetRows.value)), placeholderKeys(sql)),
    };
    status.value = "";
  } catch (e) {
    if (!live() || isAbort(e)) return;
    histErr.value = status.value || (e instanceof Error ? e.message : String(e));
    status.value = "";
    histPreview.value = { ...histPreview.value, rows: [] };
  } finally {
    if (live()) busy.value = false;
  }
}

function setSheetRows(rows: Record<string, unknown>[]) {
  const next = rows || [];
  if (JSON.stringify(next) === JSON.stringify(sheetRows.value)) return;
  sheetRows.value = next;
  if (sqlOpen.value && histPreview.value?.sql) void runPreview("hist");
  // ponytail: re-preview every attached SQL on sheet change; debounce if many cards
  for (const p of history.value.flatMap((m) => m.previews || [])) void runPreviewOn(p);
}

function onWriteClick(p: Preview) {
  if (!p.armed) {
    p.armed = true;
    return;
  }
  p.armed = false;
  void writeGrist(p);
}

function onHistWrite() {
  if (!histWriteArmed.value) {
    histWriteArmed.value = true;
    return;
  }
  histWriteArmed.value = false;
  void writeGrist(histPreview.value);
}

async function tableColIds(): Promise<string[]> {
  const g = window.grist;
  try {
    const tableId = await g?.getTable()?.getTableId();
    const table = tableId && g?.docApi?.fetchTable ? await g.docApi.fetchTable(tableId) : null;
    if (table) return Object.keys(table).filter((k) => k !== "id" && k !== "manualSort");
  } catch {
    /* ponytail: onRecords keys if fetchTable is missing */
  }
  return [...new Set([...sheetColumns(sheetRows.value), ...extraCols.value])];
}

async function ensureGristColumns(want: string[], have: string[]) {
  const add = missingColumns(have, want);
  if (!add.length) return have;
  const g = window.grist;
  if (!g?.docApi?.applyUserActions || !g.getTable) {
    throw new Error(`Add columns in Grist: ${add.join(", ")}`);
  }
  const tableId = await g.getTable().getTableId();
  await g.docApi.applyUserActions(
    add.map((c) => ["AddVisibleColumn", tableId, c, { type: "Text", isFormula: false }]),
  );
  extraCols.value = [...new Set([...extraCols.value, ...add])];
  return [...have, ...add];
}

async function writeGrist(preview: Preview | null) {
  if (busy.value || !preview?.sql) return;
  startBusy();
  try {
    const have = inGrist() && window.grist?.getTable ? await tableColIds() : sheetColumns(sheetRows.value);
    const rows = collapseByKeys(remapCols(preview.rows || [], have), placeholderKeys(preview.sql));
    const want = [...new Set(rows.flatMap((r) => Object.keys(r)))];
    if (inGrist() && window.grist?.getTable) {
      await ensureGristColumns(want, have);
      const keys = placeholderKeys(preview.sql);
      const recs = upsertRecords(rows, undefined, keys);
      if (!keys.length || !recs.length) {
        setStatus(keys.length ? "No matching rows to write." : "SQL has no {{column}}.");
        return;
      }
      if (recs.length) {
        const upsert = window.grist.getTable().upsert(recs, { add: false, update: true, onMany: "all" });
        await Promise.race([
          upsert,
          new Promise((_, reject) => setTimeout(() => reject(new Error("Grist upsert timed out")), 8000)),
        ]);
      }
      status.value = "";
      return;
    }
    const recs = upsertRecords(rows, undefined, placeholderKeys(preview.sql));
    const key = Object.keys(recs[0]?.require || {})[0] || "Email";
    await postJson("/api/grist/write", { rows, key });
    status.value = "";
  } catch (e) {
    if (!isAbort(e)) setStatus(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
    bumpDebug("write");
  }
}

function restyleGristChrome() {
  const frame = window.frameElement;
  if (!(frame instanceof HTMLElement)) return;
  const section = frame.closest(".viewsection_content");
  if (!(section instanceof HTMLElement)) return;
  section.classList.add("sih-chat-section");
  const doc = frame.ownerDocument;
  if (doc.getElementById("sih-chat-section-css")) return;
  const style = doc.createElement("style");
  style.id = "sih-chat-section-css";
  // ponytail: Grist title uses margin-left:-16px and overflow:visible, which paints out of the layout cell.
  style.textContent = `
    .sih-chat-section { overflow: hidden; min-width: 0; min-height: 0; }
    .sih-chat-section > .viewsection_title { min-height: 18px; margin-left: 0; margin-bottom: 12px; overflow: hidden; }
    .sih-chat-section > .view_data_pane_container { min-width: 0; min-height: 0; overflow: hidden; }
    .sih-chat-section .custom_view_container { overflow: hidden; min-width: 0; min-height: 0; }
  `;
  doc.head.appendChild(style);
}

onMounted(() => {
  (window as typeof window & { __sihSetSheetRows: (rows: Record<string, unknown>[]) => void }).__sihSetSheetRows =
    setSheetRows;
  if (inGrist() && window.grist) {
    restyleGristChrome();
    window.grist.ready({ requiredAccess: "full" });
    window.grist.onRecords((records) => setSheetRows(records || []), {
      includeColumns: "normal",
      format: "rows",
      keepEncoded: false,
    });
  }
  loadSavedSql();
  loadModels();
});
</script>

<template>
  <UApp>
    <div class="flex h-[100dvh] min-h-0 min-w-0 flex-col overflow-hidden">
    <UChatPalette class="@container min-h-0 min-w-0 flex-1 overflow-hidden bg-default text-default" :ui="paletteUi">
      <a href="#chat-prompt" class="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:m-2 focus:rounded-md focus:bg-elevated focus:px-3 focus:py-2">
        Skip to prompt
      </a>
      <div class="flex shrink-0 items-center gap-1 px-2 pt-0.5">
        <div class="relative size-8 shrink-0">
          <UButton
            data-testid="sql-sidebar"
            icon="i-lucide-panel-left"
            color="neutral"
            variant="ghost"
            size="sm"
            class="size-8 [&_svg]:size-4"
            aria-label="SQL history"
            @click="sqlOpen = true"
          />
          <span v-for="id in plusOnes" :key="id" class="sih-plus-1 pointer-events-none absolute -right-0.5 -top-1 z-10 text-sm font-bold text-success">+1</span>
        </div>
        <p
          data-testid="status"
          class="min-w-0 flex-1 truncate text-sm"
          :class="status ? 'text-error' : 'invisible'"
          aria-live="polite"
        >
          {{ status || "\u00a0" }}
        </p>
        <UButton
          data-testid="upload-open"
          icon="i-lucide-rocket"
          color="neutral"
          variant="ghost"
          size="sm"
          class="size-8 shrink-0 [&_svg]:size-4"
          aria-label="上传"
          @click="uploadOpen = true"
        />
      </div>
      <pre data-testid="log" class="sr-only">{{ logText }}</pre>
      <pre data-testid="sheet-cols" class="sr-only">{{ sheetColumns(sheetRows).join(",") }}</pre>

      <UChatMessages
        v-if="chatMessages.length || busy"
        :messages="chatMessages"
        :status="promptStatus"
        :user="{ ui: userUi }"
        :assistant="{ ui: assistantUi, avatar: mascotAvatar }"
        compact
        class="min-h-0 min-w-0 flex-1 overflow-y-auto px-2 pt-3"
      >
        <template #content="{ message }">
          <template v-if="message.role === 'assistant'">
            <template v-for="(part, i) in message.parts || []" :key="i">
              <UChatReasoning v-if="part.type === 'reasoning'" :text="part.text" :streaming="isLive(message.id)" />
              <details v-else-if="part.type === 'text' && part.text" class="text-[0.9375rem] leading-6">
                <summary class="cursor-pointer py-0.5 text-sm text-muted">回复</summary>
                <p class="max-h-32 overflow-auto whitespace-pre-wrap break-words">{{ part.text }}</p>
              </details>
            </template>
            <div v-if="msgTools(message).length" data-testid="chat-tools">
              <UChatTool
                v-for="(t, ti) in msgTools(message)"
                :key="ti"
                :text="t.output ? `Ran ${t.name}` : `Running ${t.name}`"
                :suffix="toolSuffix(t)"
                variant="inline"
                :streaming="isLive(message.id) && !t.output"
              >
                <pre class="max-h-40 overflow-auto font-mono text-xs whitespace-pre-wrap break-words">{{ toolBody(t) }}</pre>
              </UChatTool>
            </div>
            <UChatTool
              v-for="(p, qi) in history[Number(message.id)]?.previews || message.previews || []"
              :key="qi"
              variant="card"
              icon="i-lucide-database"
              :text="(p.note || 'Query').split('\n')[0]"
              :suffix="p.db"
              :default-open="true"
              :ui="sqlToolUi"
              class="mt-2"
            >
              <div class="relative">
                <div :class="p.armed ? 'pointer-events-none select-none blur-sm' : ''">
                  <details>
                    <summary class="cursor-pointer text-muted">SQL</summary>
                    <pre data-testid="sql-text" class="max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-default">{{ `[${p.db}] ${p.sql}` }}</pre>
                  </details>
                  <div data-testid="sql-preview" class="min-w-0 overflow-auto pt-2 text-sm tabular-nums">
                    <span class="sr-only">{{ JSON.stringify(p.rows) }}</span>
                    <p v-if="p.err" class="text-error">{{ p.err }}</p>
                    <UTable v-else-if="p.rows?.length" :data="p.rows" />
                    <p v-else class="text-muted">0 rows</p>
                  </div>
                </div>
                <button
                  v-if="p.armed"
                  data-testid="write-grist"
                  type="button"
                  class="absolute inset-0 z-10 flex items-center justify-center text-3xl font-semibold text-success"
                  :disabled="busy"
                  @click="onWriteClick(p)"
                >
                  确认写入？
                </button>
              </div>
              <template #actions>
                <UButton
                  data-testid="sql-exec"
                  size="xs"
                  color="primary"
                  variant="ghost"
                  icon="i-lucide-play"
                  :loading="busy"
                  :disabled="busy || !p.sql"
                  @click="runPreviewOn(p)"
                >
                  执行
                </UButton>
                <UButton
                  data-testid="sql-save"
                  size="xs"
                  :color="isSaved(p) ? 'success' : 'neutral'"
                  variant="ghost"
                  :icon="isSaved(p) ? 'i-lucide-check' : 'i-lucide-bookmark'"
                  :loading="p.saving"
                  :disabled="busy || p.saving || isSaved(p)"
                  @click="savePreview(p)"
                >
                  {{ isSaved(p) ? "已存" : "存 history" }}
                </UButton>
                <UButton v-if="p.rows?.length && !p.armed" data-testid="write-grist" type="button" size="xs" color="success" :disabled="busy" @click="onWriteClick(p)">
                  写入
                </UButton>
              </template>
            </UChatTool>
          </template>
          <p v-else class="whitespace-pre-wrap break-words text-[0.9375rem] leading-6">
            {{ message.parts?.map((p: { text?: string }) => p.text).join("") || "" }}
          </p>
        </template>
        <template #actions="{ message }">
          <template v-if="message.role === 'user'">
            <UTooltip text="Revert">
              <UButton size="sm" color="neutral" variant="ghost" icon="i-lucide-undo-2" aria-label="Revert" :disabled="busy" @click="revertAt(Number(message.id))" />
            </UTooltip>
            <UTooltip text="Rerun">
              <UButton size="sm" color="neutral" variant="ghost" icon="i-lucide-rotate-cw" aria-label="Rerun" :disabled="busy" @click="rerunAt(Number(message.id))" />
            </UTooltip>
          </template>
          <template v-else>
            <UTooltip text="Copy">
              <UButton size="sm" color="neutral" variant="ghost" icon="i-lucide-copy" aria-label="Copy" @click="copyMsg(message)" />
            </UTooltip>
            <UTooltip text="Rerun">
              <UButton size="sm" color="neutral" variant="ghost" icon="i-lucide-rotate-cw" aria-label="Rerun" :disabled="busy" @click="rerunAt(Number(message.id))" />
            </UTooltip>
          </template>
        </template>
      </UChatMessages>
      <div v-else class="flex min-h-0 min-w-0 flex-1 items-center justify-center px-2 pt-3">
        <img :src="mascot" alt="" class="w-36 max-w-[40%] dark:invert" />
      </div>

      <template #prompt>
          <div v-if="pendingAsk" data-testid="ask-card" class="flex flex-col gap-2 rounded-md p-2 ring-2 ring-primary">
          <p data-testid="ask-question" class="text-[0.9375rem] leading-6">{{ pendingAsk?.question }}</p>
          <div v-if="pendingAsk?.options?.length" class="flex flex-wrap gap-1.5">
            <UButton
              v-for="opt in pendingAsk.options"
              :key="opt"
              type="button"
              size="sm"
              color="neutral"
              variant="outline"
              @click="answerAsk(opt)"
            >
              {{ opt }}
            </UButton>
          </div>
          <div id="chat-prompt" data-testid="chat-input">
            <UChatPrompt
              v-model="draft"
              aria-label="Answer"
              autocomplete="off"
              placeholder="Message"
              :autofocus="false"
              @submit="answerAsk"
            >
              <UChatPromptSubmit aria-label="Send" :status="promptStatus" :disabled="!draft.trim()" @stop="stopTurn" />
            </UChatPrompt>
          </div>
          <UButton data-testid="ask-submit" type="button" color="neutral" variant="ghost" size="sm" :disabled="!canSend" @click="answerAsk">
            Answer
          </UButton>
        </div>

        <div v-else class="flex flex-col gap-2">
          <pre v-if="!hasSql" data-testid="sql-text" class="sr-only">No SQL yet.</pre>
          <div v-if="!hasSql" data-testid="sql-preview" class="sr-only">[]</div>
          <div v-if="!sqlOpen" data-testid="sql-saved" class="sr-only" />

          <div id="chat-prompt" data-testid="chat-input">
            <UChatPrompt
              v-model="draft"
              aria-label="Message"
              autocomplete="off"
              placeholder="Message"
              :autofocus="false"
              class="min-w-0 overflow-hidden rounded-md ring-2 ring-primary"
              @submit="onSubmit"
            >
              <UChatPromptSubmit aria-label="Send" :status="promptStatus" :disabled="!draft.trim()" @stop="stopTurn" />
              <template #footer>
                <UFieldGroup size="sm" class="min-w-0 w-full flex-1 overflow-hidden">
                  <USelectMenu
                    v-model="model"
                    name="model"
                    data-testid="model"
                    aria-label="Model"
                    :items="modelItems"
                    value-key="value"
                    variant="ghost"
                    class="min-w-0 flex-1"
                    :ui="{ content: 'ring-2 ring-primary' }"
                  >
                    <template #item-trailing="{ item }">
                      <UButton
                        v-if="item.value === LOCAL_CFG"
                        data-testid="openai-open"
                        size="xs"
                        color="neutral"
                        variant="outline"
                        label="配置"
                        @click.stop.prevent="openOpenai"
                      />
                    </template>
                  </USelectMenu>
                  <USelect v-model="effort" name="effort" data-testid="effort" aria-label="Effort" :items="effortItems" value-key="value" variant="ghost" class="min-w-0 w-24 shrink-0" />
                </UFieldGroup>
              </template>
            </UChatPrompt>
          </div>
        </div>
      </template>
    </UChatPalette>
    </div>

    <USlideover v-model:open="sqlOpen" title="SQL history" side="left" :ui="slideUi">
      <template #body>
        <div class="@container flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-hidden p-2 @xl:flex-row">
            <section class="min-h-0 min-w-0 shrink-0 overflow-hidden rounded-md ring-1 ring-primary @xl:flex @xl:w-56 @xl:shrink-0 @xl:flex-col">
              <div data-testid="sql-saved" class="max-h-36 overflow-auto px-2 pb-2 @xl:max-h-none @xl:min-h-0 @xl:flex-1">
                <ul v-if="savedByCreated.length" class="min-w-0">
                  <li v-for="item in savedByCreated" :key="item.id" class="flex min-w-0 items-center gap-1">
                    <div class="flex min-w-0 w-0 flex-1 cursor-pointer flex-col overflow-hidden" @click="runSaved(item)">
                      <input
                        class="w-full min-w-0 truncate bg-transparent text-sm outline-none"
                        :value="item.note"
                        aria-label="备注"
                        @click.stop
                        @change="renameSaved(item.id, ($event.target as HTMLInputElement).value)"
                      />
                      <span data-testid="sql-run" class="w-full truncate text-xs font-normal text-muted">{{ createdAt(item.created) }}</span>
                    </div>
                    <UButton
                      data-testid="sql-delete"
                      type="button"
                      size="sm"
                      class="shrink-0"
                      :color="deleteArmed === item.id ? 'error' : 'neutral'"
                      variant="ghost"
                      :icon="deleteArmed === item.id ? undefined : 'i-lucide-trash'"
                      :aria-label="deleteArmed === item.id ? '确认删除' : 'Delete'"
                      @click="onDeleteClick(item.id)"
                    >
                      {{ deleteArmed === item.id ? "确认删除" : "" }}
                    </UButton>
                  </li>
                </ul>
              </div>
            </section>
            <section class="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-md ring-1 ring-primary">
              <template v-if="hasHistSql">
                <div class="flex min-h-0 min-w-0 flex-1 flex-col" :class="histWriteArmed ? 'pointer-events-none select-none blur-sm' : ''">
                  <details class="shrink-0 px-3">
                    <summary class="cursor-pointer py-2 text-sm text-muted">Query</summary>
                    <pre data-testid="hist-sql-text" class="max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-default">{{ `[${histPreview?.db}] ${histPreview?.sql}` }}</pre>
                  </details>
                  <div data-testid="hist-sql-preview" class="min-h-0 min-w-0 flex-1 overflow-auto px-3 text-sm tabular-nums">
                    <span class="sr-only">{{ JSON.stringify(histRows) }}</span>
                    <p v-if="histErr" class="text-error">{{ histErr }}</p>
                    <UTable v-else-if="hasHistRows" :data="histRows" />
                    <p v-else class="text-muted">0 rows</p>
                  </div>
                  <div v-if="hasHistRows && !histWriteArmed" class="flex shrink-0 gap-2 p-3">
                    <UButton data-testid="hist-write-grist" type="button" size="sm" color="success" :disabled="busy" @click="onHistWrite">
                      写入
                    </UButton>
                  </div>
                </div>
                <button
                  v-if="histWriteArmed"
                  data-testid="hist-write-grist"
                  type="button"
                  class="absolute inset-0 z-10 flex items-center justify-center text-3xl font-semibold text-success"
                  :disabled="busy"
                  @click="onHistWrite"
                >
                  确认写入？
                </button>
              </template>
            </section>
          </div>
        </div>
      </template>
    </USlideover>
    <UploadModal v-model:open="uploadOpen" :role="role" :rows="sheetRows" />
    <UModal v-model:open="openaiOpen" title="本地模型" description="OpenAI 兼容接口" :ui="{ footer: 'justify-end' }">
      <template #body>
        <div class="flex flex-col gap-3">
          <UFormField label="Base URL" required>
            <UInput v-model="openaiUrl" placeholder="http://127.0.0.1:25890/v1" autocomplete="off" />
          </UFormField>
          <UFormField label="API key">
            <UInput v-model="openaiKey" type="password" placeholder="可选" autocomplete="off" />
          </UFormField>
          <p v-if="openaiErr" class="text-sm text-error">{{ openaiErr }}</p>
        </div>
      </template>
      <template #footer="{ close }">
        <UButton label="取消" color="neutral" variant="outline" @click="close" />
        <UButton data-testid="openai-connect" label="连接" :loading="openaiBusy" @click="saveOpenai" />
      </template>
    </UModal>
  </UApp>
</template>
