import { test, expect, type Page } from "@playwright/test";

async function login(page: Page, email: string) {
  await page.request.post("/api/e2e/session", { data: { email } });
}

test("boss prepare shows diff and commit succeeds", async ({ page }) => {
  await login(page, "boss@hku.hk");
  await page.goto("/submit");
  await page.request.post("/api/submit/prepare");
  await expect(page.getByTestId("diff")).toBeVisible();
  await page.getByTestId("commit").click();
  await expect(page.getByTestId("commit-ok")).toBeVisible();
});

test("keeper commit is 403", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  const res = await page.request.post("/api/submit/commit");
  expect(res.status()).toBe(403);
});
