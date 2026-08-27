import { test, expect, type Page } from "@playwright/test";

async function login(page: Page, email: string) {
  await page.request.post("/api/e2e/session", { data: { email } });
}

test("unauthenticated chat redirects to guest", async ({ page }) => {
  const res = await page.request.get("/chat", { maxRedirects: 0 });
  expect(res.status()).toBe(302);
  expect(res.headers()["location"]).toContain("/api/auth/guest");
});

test("keeper submit has no commit", async ({ page }) => {
  await login(page, "keeper@hku.hk");
  await page.goto("/submit");
  await expect(page.getByTestId("commit")).toHaveCount(0);
});

test("boss submit has commit", async ({ page }) => {
  await login(page, "boss@hku.hk");
  await page.goto("/submit");
  await expect(page.getByTestId("commit")).toBeVisible();
});
