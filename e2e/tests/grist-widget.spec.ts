import { test, expect, type Page } from "@playwright/test";

const email = process.env.SIH_E2E_EMAIL || "";
const doc = process.env.SIH_GRIST_PATH || "/o/docs/qTEgHD3EZU2y/SIH-people";

async function mockChat(page: Page) {
  await page.route("**/api/chat/turn", async (route) => {
    const raw = route.request().postData() || "";
    if (raw.includes("rp00401") || raw.includes("demo@hku.hk")) {
      await route.fulfill({ status: 400, json: { detail: "cell values must not be on chat/turn" } });
      return;
    }
    const body = route.request().postDataJSON() as { tool_results?: unknown[] };
    if (body.tool_results?.length) {
      await route.fulfill({
        json: {
          text: "Lookup by selected RP_no.",
          tool_calls: [],
          previews: [{ sql: 'SELECT unnest(ARRAY[{{RP_no}}]) AS "RP_no", \'e2e-sql\' AS "Name"', db: "hub" }],
        },
      });
      return;
    }
    await route.fulfill({
      json: {
        text: "",
        tool_calls: [
          {
            id: "stub-ask",
            name: "ask_question",
            arguments: { question: "Which source?", kind: "single", options: ["staff", "scopus"] },
          },
        ],
        previews: [],
      },
    });
  });
}

test("grist page: chat SQL, row RP_no bind, exec, write back", async ({ page }) => {
  test.skip(!email, "set SIH_E2E_EMAIL to a manager/maintainer");
  await page.setViewportSize({ width: 1400, height: 900 });
  await mockChat(page);
  await page.goto(`/api/e2e/login?email=${encodeURIComponent(email)}`);
  await page.goto(doc);
  await page.keyboard.press("Escape");

  const chat = page.frameLocator("iframe.custom_view");
  await expect(chat.getByTestId("chat-input")).toBeVisible({ timeout: 20_000 });

  await chat.getByTestId("chat-input").getByRole("textbox").fill("look up this person");
  await chat.getByTestId("chat-input").getByRole("textbox").press("Enter");
  await expect(chat.getByTestId("ask-card")).toBeVisible();
  await chat.getByTestId("chat-input").getByRole("textbox").fill("staff");
  await chat.getByTestId("ask-submit").click();
  await expect(chat.getByTestId("sql-text")).toContainText("{{RP_no}}");

  await page.getByText("rp00401", { exact: true }).first().click();
  const grant = page.getByTestId("test-config-widget-access-accept");
  if (await grant.isVisible().catch(() => false)) await grant.click();
  await expect(chat.getByTestId("sql-preview")).toContainText("e2e-sql");
  await expect(chat.getByTestId("sql-preview")).toContainText("rp00401");
  await expect(chat.getByTestId("sql-preview")).not.toContainText("{{RP_no}}");

  await chat.getByTestId("write-grist").click();
  await chat.getByTestId("write-grist").click();
  await expect(page.getByText("e2e-sql").first()).toBeVisible();
});
