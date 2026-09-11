import { expect, type Page, type TestInfo } from "@playwright/test";

export async function verifyRequestStates(page: Page, info: TestInfo) {
  await page.goto("/app/admin/jobs");
  await page
    .getByLabel("Created after", { exact: true })
    .fill("2100-01-01T00:00");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByText("No jobs found.", { exact: true })).toBeVisible();
  await page.screenshot({
    path: info.outputPath("empty-jobs.png"),
    fullPage: true,
  });
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/admin/jobs?**", async (route) => {
    await gate;
    await route.continue();
  });
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("status", { name: "Loading records" }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("loading-jobs.png"),
    fullPage: true,
  });
  release();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.unroute("**/admin/jobs?**");
  // Fault injection is test-only: all successful data still comes from the running API.
  await page.route("**/admin/jobs?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { message: "Jobs are temporarily unavailable" },
      }),
    }),
  );
  await page.reload();
  await expect(
    page.getByText("Jobs are temporarily unavailable"),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("error-jobs.png"),
    fullPage: true,
  });
  await page.unroute("**/admin/jobs?**");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await expect(page.locator(".error-state")).toHaveCount(0);
}

export async function verifyResponsiveStates(page: Page, info: TestInfo) {
  await page.route("**/admin/queue-controls", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { message: "Queue controls are temporarily unavailable" },
      }),
    }),
  );
  await page.goto("/app/admin/queues");
  await expect(
    page.getByText("Queue controls are temporarily unavailable"),
  ).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await expect(page.getByText("Accepting claims", { exact: true })).toHaveCount(
    0,
  );
  for (const button of await page.locator("tbody button").all())
    await expect(button).toBeDisabled();
  await page.screenshot({
    path: info.outputPath("partial-queues.png"),
    fullPage: true,
  });
  await page.unroute("**/admin/queue-controls");
  for (const width of [320, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of [
      "admin",
      "admin/jobs",
      "admin/queues",
      "admin/users",
      "password",
    ]) {
      await page.goto(`/app/${route}`);
      await expect(page.locator("h1")).toBeVisible();
      await expect(page.locator(".table-skeleton")).toHaveCount(0);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
        `${route} at ${width}px`,
      ).toBe(true);
      await page.mouse.move(0, 0);
      await page.screenshot({
        path: info.outputPath(`${route.replaceAll("/", "-")}-${width}.png`),
        fullPage: true,
      });
    }
  }
  await page.goto("/app/admin");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByLabel("Role", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toHaveAttribute("aria-expanded", "false");
}
