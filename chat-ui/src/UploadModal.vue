<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { sheetColumns } from "@sheet";

type Tpl = { id: number; name: string; account: string; container: string; path: string };
type Hist = { id: number; created: number; author: string; kind: string; path: string };
type Req = { id: number; created: number; author: string; path: string; columns: string[] };

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{ role: string; rows: Record<string, unknown>[] }>();

const dest = ref("azure");
const screen = ref<"pick" | "add" | "cols">("pick");
const templates = ref<Tpl[]>([]);
const templateId = ref<number | undefined>(undefined);
const account = ref("");
const container = ref("");
const path = ref("powerbi/users.csv");
const accountKey = ref("");
const remoteCols = ref<string[]>([]);
const selected = ref<string[]>([]);
const keyGrist = ref("email");
const keyCsv = ref("email");
const err = ref("");
const busy = ref(false);
const armed = ref(false);
const history = ref<Hist[]>([]);
const requests = ref<Req[]>([]);
const rollbackArmed = ref<number | null>(null);

const isManager = computed(() => props.role === "manager");
const sheetCols = computed(() => sheetColumns(props.rows));
const destItems = [
  { label: "Azure", value: "azure" },
  { label: "Upstream", value: "db" },
];
const colItems = computed(() => sheetCols.value.map((c) => ({ label: c, value: c })));
const slideUi = { content: "w-full max-w-full overflow-hidden" };
const tabUi = {
  list: "relative z-10 w-full rounded-none border-0 bg-transparent p-0",
  indicator:
    "top-0 -bottom-0.5 h-auto rounded-b-none rounded-t-md border-2 border-b-0 border-primary bg-default shadow-none",
  trigger: "flex-1 rounded-none data-[state=active]:text-primary",
};
const deleteArmed = ref<number | null>(null);

watch(open, (v) => {
  if (!v) return;
  dest.value = "azure";
  screen.value = "pick";
  templateId.value = undefined;
  err.value = "";
  armed.value = false;
  rollbackArmed.value = null;
  deleteArmed.value = null;
  remoteCols.value = [];
  selected.value = [];
  void loadMeta();
});

watch(dest, () => {
  screen.value = "pick";
  err.value = "";
  armed.value = false;
});

function createdAt(t?: number) {
  return t ? new Date(t * 1000).toLocaleString() : "";
}

async function loadMeta() {
  const [t, r, h] = await Promise.all([
    fetch("/api/upload/templates"),
    fetch("/api/upload/requests"),
    isManager.value ? fetch("/api/upload/history") : Promise.resolve(null),
  ]);
  if (t.ok) templates.value = (await t.json()).templates || [];
  if (r.ok) requests.value = (await r.json()).requests || [];
  if (h && h.ok) history.value = (await h.json()).history || [];
}

function connBody() {
  return {
    dest: dest.value,
    template_id: templateId.value || undefined,
    account: account.value,
    container: container.value,
    path: path.value,
    account_key: accountKey.value || undefined,
    columns: selected.value,
  };
}

function startAdd() {
  templateId.value = undefined;
  account.value = "";
  container.value = "";
  path.value = "powerbi/users.csv";
  accountKey.value = "";
  err.value = "";
  screen.value = "add";
}

function useTemplate(t: Tpl) {
  templateId.value = t.id;
  account.value = t.account;
  container.value = t.container;
  path.value = t.path;
  accountKey.value = "";
  void onConnect();
}

async function renameTemplate(t: Tpl, raw: string) {
  const name = raw.trim().slice(0, 80);
  if (!name || name === t.name) return;
  const r = await fetch(`/api/upload/templates/${t.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) {
    err.value = "rename failed";
    return;
  }
  t.name = name;
}

async function deleteTemplate(id: number) {
  if (deleteArmed.value !== id) {
    deleteArmed.value = id;
    return;
  }
  const r = await fetch(`/api/upload/templates/${id}`, { method: "DELETE" });
  if (!r.ok) {
    err.value = "delete failed";
    deleteArmed.value = null;
    return;
  }
  deleteArmed.value = null;
  if (templateId.value === id) templateId.value = undefined;
  await loadMeta();
}

function backPick() {
  templateId.value = undefined;
  screen.value = "pick";
  err.value = "";
  armed.value = false;
}

async function onConnect() {
  err.value = "";
  busy.value = true;
  try {
    const r = await fetch("/api/upload/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(connBody()),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "connect failed");
    remoteCols.value = data.columns || [];
    const match = sheetCols.value.filter((c) => remoteCols.value.some((x: string) => x.toLowerCase() === c.toLowerCase()));
    selected.value = match.length ? match : [...sheetCols.value];
    keyGrist.value = data.key_grist || selected.value[0] || "email";
    keyCsv.value = data.key_csv || remoteCols.value[0] || keyGrist.value;
    if (screen.value === "add") await saveTemplate();
    screen.value = "cols";
  } catch (e) {
    err.value = e instanceof Error ? e.message : "connect failed";
  } finally {
    busy.value = false;
  }
}

async function saveTemplate() {
  const name = `${account.value}/${path.value}`.slice(0, 80);
  await fetch("/api/upload/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...connBody(), name }),
  });
  await loadMeta();
}

async function sendRequest() {
  err.value = "";
  const r = await fetch("/api/upload/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...connBody(),
      columns: selected.value,
      key_grist: keyGrist.value,
      key_csv: keyCsv.value,
      rows: props.rows,
    }),
  });
  if (!r.ok) {
    err.value = "request failed";
    return;
  }
  open.value = false;
}

async function commit() {
  if (!armed.value) {
    armed.value = true;
    return;
  }
  err.value = "";
  busy.value = true;
  try {
    const r = await fetch("/api/upload/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...connBody(),
        confirm: true,
        columns: selected.value,
        key_grist: keyGrist.value,
        key_csv: keyCsv.value,
        rows: props.rows,
      }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "upload failed");
    armed.value = false;
    await loadMeta();
    screen.value = "pick";
  } catch (e) {
    err.value = e instanceof Error ? e.message : "upload failed";
  } finally {
    busy.value = false;
  }
}

async function rollback(id: number) {
  if (rollbackArmed.value !== id) {
    rollbackArmed.value = id;
    return;
  }
  err.value = "";
  const r = await fetch(`/api/upload/history/${id}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true, template_id: templateId.value || undefined, account_key: accountKey.value || undefined }),
  });
  if (!r.ok) {
    err.value = "rollback failed";
    rollbackArmed.value = null;
    return;
  }
  rollbackArmed.value = null;
  await loadMeta();
}

async function commitRequest(id: number) {
  if (!armed.value) {
    armed.value = true;
    return;
  }
  err.value = "";
  busy.value = true;
  try {
    const r = await fetch("/api/upload/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true, request_id: id }),
    });
    if (!r.ok) throw new Error("upload failed");
    armed.value = false;
    await loadMeta();
    screen.value = "pick";
  } catch (e) {
    err.value = e instanceof Error ? e.message : "upload failed";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <USlideover v-model:open="open" side="right" title="上传" :close="false" :ui="slideUi">
    <template #content="{ close }">
      <div class="flex h-full min-h-0 flex-col p-2">
        <div class="flex min-h-0 min-w-0 flex-1 gap-1">
          <div class="flex min-h-0 min-w-0 flex-1 flex-col">
            <div data-testid="upload-dest" class="shrink-0">
              <UTabs
                v-model="dest"
                variant="link"
                color="primary"
                size="md"
                :content="false"
                :items="destItems"
                class="w-full"
                :ui="tabUi"
              />
            </div>
            <div
              class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-b-md border-2 border-primary p-2 transition-[border-radius] duration-200"
              :class="dest === 'azure' ? 'rounded-tr-md' : 'rounded-tl-md'"
            >
      <p v-if="err" class="pb-2 text-sm text-error" data-testid="upload-err">{{ err }}</p>

      <p v-if="dest === 'db'" class="py-6 text-center text-sm text-muted">稍后</p>

      <div v-else-if="screen === 'pick'" class="flex min-h-0 flex-1 flex-col gap-3">
        <div data-testid="upload-saved" class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md ring-1 ring-primary">
          <div class="flex shrink-0 items-center gap-1 px-2 pt-1">
            <p class="min-w-0 flex-1 text-sm">已存链接</p>
            <UButton icon="i-lucide-plus" color="neutral" variant="ghost" size="xs" aria-label="新增连接" @click="startAdd" />
          </div>
          <p v-if="!templates.length" class="px-2 pb-2 text-sm text-muted">暂无已存链接</p>
          <ul v-else class="min-h-0 flex-1 overflow-auto px-1 pb-1">
            <li v-for="t in templates" :key="t.id" class="flex min-w-0 items-center gap-1">
              <div class="flex min-w-0 w-0 flex-1 cursor-pointer flex-col overflow-hidden" @click="useTemplate(t)">
                <input
                  class="w-full min-w-0 truncate bg-transparent text-sm outline-none"
                  :value="t.name"
                  aria-label="备注"
                  @click.stop
                  @change="renameTemplate(t, ($event.target as HTMLInputElement).value)"
                />
                <span class="w-full truncate text-xs text-muted">{{ t.account }}/{{ t.container }}/{{ t.path }}</span>
              </div>
              <UButton
                data-testid="upload-saved-delete"
                type="button"
                size="sm"
                class="shrink-0"
                :color="deleteArmed === t.id ? 'error' : 'neutral'"
                variant="ghost"
                :icon="deleteArmed === t.id ? undefined : 'i-lucide-trash'"
                :aria-label="deleteArmed === t.id ? '确认删除' : 'Delete'"
                @click.stop="deleteTemplate(t.id)"
              >
                {{ deleteArmed === t.id ? "确认删除" : "" }}
              </UButton>
            </li>
          </ul>
        </div>
        <div v-if="isManager && requests.length" class="flex shrink-0 flex-col gap-1">
          <p class="text-sm text-muted">请求</p>
          <div v-for="q in requests" :key="q.id" class="flex min-w-0 items-center gap-1">
            <span class="min-w-0 flex-1 truncate text-sm">{{ q.author }} · {{ q.path }}</span>
            <UButton size="sm" data-testid="upload-commit-request" :disabled="busy" @click="commitRequest(q.id)">
              {{ armed ? "确认上传？" : "上传" }}
            </UButton>
          </div>
        </div>
        <div v-if="isManager" data-testid="upload-history" class="flex max-h-36 shrink-0 flex-col gap-1 overflow-hidden">
          <p class="text-sm font-medium">回退</p>
          <p v-if="!history.length" class="text-sm text-muted">暂无上传记录</p>
          <div v-else class="min-h-0 overflow-auto">
            <div v-for="h in history" :key="h.id" class="flex min-w-0 items-center gap-1 py-0.5">
              <span class="min-w-0 flex-1 truncate text-sm">{{ createdAt(h.created) }} · {{ h.path }}</span>
              <UButton data-testid="upload-rollback" size="sm" color="neutral" variant="outline" :disabled="busy" @click="rollback(h.id)">
                {{ rollbackArmed === h.id ? "确认回退？" : "回退" }}
              </UButton>
            </div>
          </div>
        </div>
      </div>

      <div v-else-if="screen === 'add'" class="flex flex-col gap-2">
        <UInput v-model="account" placeholder="account-name" autocomplete="off" />
        <UInput v-model="container" placeholder="container" autocomplete="off" />
        <UInput v-model="path" placeholder="path" autocomplete="off" />
        <UInput v-model="accountKey" type="password" placeholder="account-key" autocomplete="off" />
        <div class="flex justify-end gap-1">
          <UButton size="sm" color="neutral" variant="ghost" @click="backPick">返回</UButton>
          <UButton data-testid="upload-connect" size="sm" :loading="busy" :disabled="busy || !account || !container || !path || !accountKey" @click="onConnect">
            连接
          </UButton>
        </div>
      </div>

      <div v-else-if="screen === 'cols'" class="flex flex-col gap-2">
        <p v-if="!sheetCols.length" class="text-sm text-muted">当前表没有列</p>
        <USelectMenu v-else v-model="selected" multiple :items="colItems" value-key="value" placeholder="列" />
        <div class="flex justify-end gap-1">
          <UButton size="sm" color="neutral" variant="ghost" @click="backPick">返回</UButton>
          <UButton v-if="!isManager" data-testid="upload-request" size="sm" :disabled="busy || !selected.length" @click="sendRequest">
            Send request
          </UButton>
          <UButton v-else data-testid="upload-commit" size="sm" :disabled="busy || !selected.length" :color="armed ? 'error' : 'primary'" @click="commit">
            {{ armed ? "确认上传？" : "上传" }}
          </UButton>
        </div>
      </div>

            </div>
          </div>
          <UButton icon="i-lucide-x" color="neutral" variant="ghost" size="xs" class="shrink-0 self-start" aria-label="Close" @click="close" />
        </div>
      </div>
    </template>
  </USlideover>
</template>
