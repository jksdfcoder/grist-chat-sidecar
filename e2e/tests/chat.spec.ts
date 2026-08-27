import { test, expect, type Page } from "@playwright/test";

async function login(page: Page, email: string) {
  await page.request.post("/api/e2e/session", { data: { email } });
}

test("chat shows used tools", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  await page.route("**/api/chat/turn", async (route) => {
    await route.fulfill({
      json: {
        text: "done",
        tool_calls: [],
        previews: [{ sql: "SELECT 1 AS ok", db: "hub" }],
        tools: [
          { name: "list_tables", arguments: { db: "hub" }, output: '[{"table":"x"}]' },
          {
            name: "preview_sql",
            arguments: { sql: "SELECT 1 AS ok", db: "hub" },
            output: '{"sql":"SELECT 1 AS ok"}',
          },
        ],
      },
    });
  });
  await page.goto("/chat");
  await page.getByTestId("chat-input").getByRole("textbox").fill("hello");
  await page.getByTestId("chat-input").getByRole("textbox").press("Enter");
  const tools = page.getByTestId("chat-tools");
  await expect(tools.getByText("Ran list_tables")).toBeVisible();
  await tools.getByRole("button", { name: /Ran list_tables/ }).click();
  await expect(tools).toContainText("list_tables --db hub");
});

test("chat revert and rerun on a user message", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  await page.goto("/chat");
  await page.getByTestId("chat-input").getByRole("textbox").fill("hello");
  await page.getByTestId("chat-input").getByRole("textbox").press("Enter");
  await expect(page.getByTestId("ask-card")).toBeVisible();
  await page.getByRole("button", { name: "Revert" }).click();
  await expect(page.getByTestId("ask-card")).toHaveCount(0);
  await expect(page.getByTestId("chat-input").getByRole("textbox")).toHaveValue("hello");
  await page.getByTestId("chat-input").getByRole("textbox").press("Enter");
  await expect(page.getByTestId("ask-card")).toBeVisible();
  await page.getByRole("button", { name: "Rerun" }).first().click();
  await expect(page.getByTestId("ask-card")).toBeVisible();
});

test("chat ask-card then sql-preview", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  await page.goto("/chat");
  await page.getByTestId("chat-input").getByRole("textbox").fill("hello");
  await page.getByTestId("chat-input").getByRole("textbox").press("Enter");
  await expect(page.getByTestId("ask-card")).toBeVisible();
  await page.getByTestId("chat-input").getByRole("textbox").fill("staff");
  await page.getByTestId("ask-submit").click();
  await expect(page.getByTestId("sql-text")).toContainText("{{Email}}");
  await expect(page.getByTestId("sql-preview")).toContainText("unbound");
  await expect(page.getByTestId("sql-exec")).toBeVisible();
  await page.getByTestId("sql-exec").click();
  await expect(page.getByTestId("sql-preview")).toContainText("unbound");
  await page.evaluate(() => {
    (window as Window & { __sihSetSheetRows: (rows: { Email: string }[]) => void }).__sihSetSheetRows([
      { Email: "a@hku.hk" },
    ]);
  });
  await expect(page.getByTestId("sql-preview")).toContainText("a@hku.hk");
  await page.getByTestId("write-grist").click();
  await expect(page.getByTestId("write-grist")).toHaveText("确认写入？");
  await page.getByTestId("write-grist").click();
  const prep = await page.request.post("/api/submit/prepare", { data: {} });
  expect(prep.ok()).toBeTruthy();
  expect(JSON.stringify(await prep.json())).toContain("a@hku.hk");
  await page.getByTestId("sql-save").click();
  await expect(page.getByTestId("sql-save")).toBeDisabled();
  await page.getByTestId("sql-sidebar").click();
  await expect(page.getByTestId("sql-saved").getByDisplayValue(/Input:/)).toBeVisible();
  await page.getByTestId("sql-delete").click();
  await expect(page.getByTestId("sql-delete")).toHaveText("确认删除");
  await page.getByTestId("sql-delete").click();
  await expect(page.getByTestId("sql-saved").getByDisplayValue(/Input:/)).toHaveCount(0);
});

test("sql-exec empty result shows 0-row hint", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  await page.route("**/api/chat/turn", async (route) => {
    await route.fulfill({
      json: {
        text: "",
        tool_calls: [],
        previews: [{ sql: "SELECT 1 AS ok FROM t WHERE id = 0", db: "hub" }],
      },
    });
  });
  await page.route("**/api/sql/preview", async (route) => {
    await route.fulfill({ json: { sql: "SELECT 1 AS ok FROM t WHERE id = 0 LIMIT 20", rows: [], db: "hub" } });
  });
  await page.goto("/chat");
  await page.getByTestId("chat-input").getByRole("textbox").fill("wos");
  await page.getByTestId("chat-input").getByRole("textbox").press("Enter");
  await expect(page.getByTestId("sql-exec")).toBeVisible();
  await expect(page.getByTestId("sql-preview")).toContainText("0 rows");
  await expect(page.getByTestId("sql-preview")).toContainText("{{列}}");
  await page.getByTestId("sql-exec").click();
  await expect(page.getByTestId("sql-preview")).toContainText("0 rows");
  await expect(page.getByTestId("sql-preview")).toContainText("hub");
});

test("sql preview binds Email without sending it to chat", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  const unbound = await page.request.post("/api/sql/preview", {
    data: { sql: "SELECT {{Email}} AS email", db: "hub" },
  });
  expect(unbound.status()).toBe(400);
  const bound = await page.request.post("/api/sql/preview", {
    data: {
      sql: "SELECT {{Email}} AS email",
      db: "hub",
      binds: { Email: ["a@hku.hk"] },
    },
  });
  expect(bound.ok()).toBeTruthy();
  const body = await bound.json();
  expect(body.rows.length).toBeGreaterThan(0);
  expect(JSON.stringify(body)).not.toContain("{{Email}}");
});

test("sql preview binds RP_no", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  const bound = await page.request.post("/api/sql/preview", {
    data: {
      sql: 'SELECT {{RP_no}} AS "RP_no"',
      db: "hub",
      binds: { RP_no: ["rp00402"] },
    },
  });
  expect(bound.ok()).toBeTruthy();
  expect(JSON.stringify(await bound.json())).toContain("rp00402");
});

test("sql history click binds current sheet input cols", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  const note = `live-bind-${Date.now()}`;
  const save = await page.request.post("/api/sql", {
    data: { sql: "SELECT {{Email}} AS email", note, db: "hub" },
  });
  expect(save.ok()).toBeTruthy();
  await page.goto("/chat");
  await page.evaluate(() => {
    (window as Window & { __sihSetSheetRows: (rows: { Email: string }[]) => void }).__sihSetSheetRows([
      { Email: "a@hku.hk" },
    ]);
  });
  await page.getByTestId("sql-sidebar").click();
  await page.getByTestId("sql-saved").locator("li").filter({ has: page.getByDisplayValue(note) }).getByTestId("sql-run").click();
  await expect(page.getByTestId("hist-sql-preview")).toContainText("a@hku.hk");
  await page.evaluate(() => {
    (window as Window & { __sihSetSheetRows: (rows: { Email: string }[]) => void }).__sihSetSheetRows([
      { Email: "b@hku.hk" },
    ]);
  });
  await page.getByTestId("sql-saved").locator("li").filter({ has: page.getByDisplayValue(note) }).getByTestId("sql-run").click();
  await expect(page.getByTestId("hist-sql-preview")).toContainText("b@hku.hk");
  await expect(page.getByTestId("hist-sql-preview")).not.toContainText("a@hku.hk");
});

test("upload rocket: dest switch, maintainer has no commit", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  await page.goto("/chat");
  await page.getByTestId("upload-open").click();
  await expect(page.getByTestId("upload-dest")).toBeVisible();
  await expect(page.getByTestId("upload-saved")).toBeVisible();
  await expect(page.getByRole("tab", { name: "Azure" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Upstream" })).toBeVisible();
  await expect(page.getByTestId("upload-request")).toHaveCount(0);
  await expect(page.getByTestId("upload-commit")).toHaveCount(0);
  await expect(page.getByTestId("upload-history")).toHaveCount(0);
  await page.keyboard.press("Escape");

  await login(page, "boss@hku.hk");
  await page.goto("/chat");
  await page.getByTestId("upload-open").click();
  await expect(page.getByTestId("upload-dest")).toBeVisible();
  await expect(page.getByTestId("upload-saved")).toBeVisible();
  await expect(page.getByTestId("upload-commit")).toHaveCount(0);
  await expect(page.getByTestId("upload-history")).toBeVisible();
});
