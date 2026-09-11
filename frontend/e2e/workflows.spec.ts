import { verifyRequestStates, verifyResponsiveStates } from "./state-checks";
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";

const temporary = "Temporary-test-password-123";
const password = "Dashboard-test-password-456";
async function login(page: Page, email: string, secret: string) {
  await page.goto("/app/login");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(secret);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/login/);
}
async function replacePassword(page: Page, old: string, next: string) {
  await expect(page).toHaveURL(/password/);
  await page.getByLabel("Current password").fill(old);
  await page.getByLabel("New password", { exact: true }).fill(next);
  await page
    .getByRole("button", { name: "Change password", exact: true })
    .click();
  await expect(page).not.toHaveURL(/password/);
}

// Run against a dedicated Compose project. Each run creates uniquely owned records.
test("dashboard-only publishing, approval, enrollment, execution, results and operations", async ({
  browser,
}, testInfo) => {
  testInfo.setTimeout(360_000);
  let env: Record<string, string> = {};
  if (process.env.E2E_ENV_FILE)
    env = Object.fromEntries(
      (await readFile(process.env.E2E_ENV_FILE, "utf8"))
        .trim()
        .split("\n")
        .map((line) => {
          const i = line.indexOf("=");
          return [line.slice(0, i), line.slice(i + 1)];
        }),
    );
  const adminPassword =
    process.env.E2E_ADMIN_PASSWORD ?? env.BOOTSTRAP_ADMIN_PASSWORD;
  if (!adminPassword) throw new Error("Set E2E_ADMIN_PASSWORD or E2E_ENV_FILE");
  const contexts = await Promise.all([
    browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:58000",
      viewport: { width: 1440, height: 1000 },
    }),
    browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:58000",
      viewport: { width: 1440, height: 1000 },
    }),
    browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:58000",
      viewport: { width: 1440, height: 1000 },
    }),
    browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:58000",
      viewport: { width: 1440, height: 1000 },
    }),
  ]);
  const [admin, publisher, producer, owner] = await Promise.all(
    contexts.map((c) => c.newPage()),
  );
  let worker: ChildProcess | undefined;
  const errors: string[] = [];
  for (const p of [admin, publisher, producer, owner])
    p.on("pageerror", (e) => errors.push(e.message));
  const suffix = Date.now().toString();
  const emails = [
    `publisher-${suffix}@example.com`,
    `producer-${suffix}@example.com`,
    `worker-${suffix}@example.com`,
  ];
  try {
    await login(
      admin,
      process.env.E2E_ADMIN_EMAIL ?? "admin@relay.local",
      adminPassword,
    );
    if (admin.url().endsWith("/password"))
      await replacePassword(admin, adminPassword, adminPassword + "-changed");
    for (const [i, role] of ["PUBLISHER", "PRODUCER", "WORKER"].entries()) {
      await admin.goto("/app/admin/users");
      await admin.getByLabel("Email", { exact: true }).fill(emails[i]);
      await admin.getByLabel("Display name").fill(role + " " + suffix);
      if (role !== "PRODUCER")
        await admin
          .getByRole("checkbox", { name: "PRODUCER", exact: true })
          .uncheck();
      await admin.getByRole("checkbox", { name: role, exact: true }).check();
      await admin
        .getByLabel("Temporary password (at least 12 characters)")
        .fill(temporary);
      await admin.getByRole("button", { name: "Save account" }).click();
      await expect(admin.getByRole("status")).toContainText("Saved");
    }
    for (const [i, p] of [publisher, producer, owner].entries()) {
      await login(p, emails[i], temporary);
      await replacePassword(p, temporary, password);
    }
    await publisher.goto("/app/publisher/releases");
    await publisher
      .getByLabel("Name", { exact: true })
      .fill("report_" + suffix);
    await publisher
      .getByLabel("Queue", { exact: true })
      .fill("reports_" + suffix);
    await publisher.getByRole("button", { name: "Create draft" }).click();
    await expect(publisher).toHaveURL(/releases\//);
    const releaseId = publisher.url().split("/").at(-1)!;
    const downloadPromise = publisher.waitForEvent("download");
    await publisher
      .getByRole("link", { name: "Download a ready-to-edit example ZIP" })
      .click();
    const zip = await downloadPromise;
    await publisher
      .getByLabel("Handler ZIP")
      .setInputFiles((await zip.path())!);
    await publisher
      .getByRole("button", { name: "Upload and validate" })
      .click();
    await expect(
      publisher.locator(".status").filter({ hasText: "PENDING APPROVAL" }),
    ).toBeVisible();
    await admin.goto(`/app/admin/releases/${releaseId}`);
    await admin.getByRole("button", { name: "Approve release" }).click();
    await admin
      .getByRole("dialog")
      .getByRole("button", { name: "Approve release", exact: true })
      .click();
    await expect(
      admin.locator(".status").filter({ hasText: /^ACTIVE$/ }),
    ).toBeVisible();
    await admin.reload();
    await expect(admin.getByText("APPROVED", { exact: true })).toBeVisible();
    await owner.goto("/app/worker/agents");
    await owner.getByLabel("Approved release").selectOption(releaseId);
    await owner.getByLabel("Agent name").fill("agent-" + suffix);
    await owner.getByRole("button", { name: "Create enrollment" }).click();
    await expect(owner.getByRole("status")).toContainText("Enrollment created");
    const command = await owner.locator("pre").innerText();
    // Parse generated environment assignments; never execute browser-provided shell text.
    const workerEnv = { ...process.env };
    for (const match of command.matchAll(/([A-Z_]+)='([^']*)'/g))
      workerEnv[match[1]] = match[2];
    const python =
      process.env.E2E_PYTHON ?? path.resolve("../.venv/bin/python");
    worker = spawn(
      python,
      [
        "-m",
        "distributed_job_queue.workers.runner",
        "--name",
        "agent-" + suffix,
        "--allow-downloaded-handler",
      ],
      { cwd: path.resolve(".."), env: workerEnv, stdio: "inherit" },
    );
    await expect(
      owner
        .getByRole("row")
        .filter({ hasText: "agent-" + suffix })
        .getByText("ONLINE", { exact: true }),
    ).toBeVisible();
    await producer.goto("/app/producer/submit");
    await producer.getByLabel("Active release").selectOption(releaseId);
    await producer.getByLabel("JSON payload").fill('{"report_id":42}');
    await producer
      .getByRole("button", { name: "Submit job", exact: true })
      .click();
    await expect(producer).toHaveURL(/jobs\//);
    await expect(
      producer
        .locator("main > div > .flex .status")
        .filter({ hasText: /^COMPLETED$/ }),
    ).toBeVisible({ timeout: 90_000 });
    const resultPromise = producer.waitForEvent("download");
    await producer.getByRole("link", { name: "Download result" }).click();
    const result = await resultPromise;
    expect(
      JSON.parse(await readFile((await result.path())!, "utf8")).input
        .report_id,
    ).toBe(42);
    await producer.screenshot({
      path: testInfo.outputPath("completed-job.png"),
      fullPage: true,
    });
    await admin.goto("/app/admin/queues");
    const queue = admin
      .getByRole("row")
      .filter({ hasText: "reports_" + suffix });
    await queue.getByRole("button", { name: "Pause queue" }).click();
    await expect(queue.getByText("Paused", { exact: true })).toBeVisible();
    await producer.goto("/app/producer/submit");
    await producer.getByLabel("Active release").selectOption(releaseId);
    await producer.getByLabel("JSON payload").fill('{"fail":true}');
    await producer.getByLabel("Maximum attempts").fill("1");
    await producer
      .getByRole("button", { name: "Submit job", exact: true })
      .click();
    await expect(producer).toHaveURL(/jobs\//);
    await expect(
      producer
        .locator("main > div > .flex .status")
        .filter({ hasText: /^QUEUED$/ }),
    ).toBeVisible();
    await queue.getByRole("button", { name: "Resume queue" }).click();
    await expect(
      producer
        .locator("main > div > .flex .status")
        .filter({ hasText: /^DEAD LETTERED$/ }),
    ).toBeVisible({ timeout: 60_000 });
    const original = producer.url();
    await producer.getByRole("button", { name: "Replay as new job" }).click();
    await producer
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel" })
      .click();
    await expect(producer).toHaveURL(original);
    await producer.getByRole("button", { name: "Replay as new job" }).click();
    await producer
      .getByRole("dialog")
      .getByRole("button", { name: "Replay job", exact: true })
      .click();
    await expect(producer).not.toHaveURL(original);
    await expect(
      producer.getByRole("link", { name: "View original job" }),
    ).toBeVisible();
    await owner.goto("/app/worker/agents");
    await owner.getByRole("button", { name: "Revoke agent" }).click();
    await owner
      .getByRole("dialog")
      .getByRole("button", { name: "Revoke agent", exact: true })
      .click();
    await expect(
      owner.getByText("Credential revoked", { exact: true }),
    ).toBeVisible();
    worker?.kill("SIGTERM");
    worker = undefined;
    await producer.goto("/app/producer/keys");
    await producer.getByLabel("Key name").fill("Acceptance key");
    await producer
      .getByRole("button", { name: "Create key", exact: true })
      .click();
    await expect(
      producer.getByRole("button", { name: "Hide key" }),
    ).toBeVisible();
    await producer.getByRole("button", { name: "Hide key" }).click();
    await producer.getByRole("button", { name: "Revoke", exact: true }).click();
    await producer
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel" })
      .click();
    await expect(producer.getByText("ACTIVE", { exact: true })).toBeVisible();
    await producer.getByRole("button", { name: "Revoke", exact: true }).click();
    await producer
      .getByRole("dialog")
      .getByRole("button", { name: "Revoke key", exact: true })
      .click();
    await expect(producer.getByText("REVOKED", { exact: true })).toBeVisible();
    await producer.goto("/app/producer/jobs");
    await producer
      .getByLabel("Status", { exact: true })
      .selectOption("COMPLETED");
    await producer.getByRole("button", { name: "Apply filters" }).click();
    await expect(producer.locator("tbody .status")).toHaveText(["COMPLETED"]);
    await producer.reload();
    await expect(producer.getByLabel("Status", { exact: true })).toHaveValue(
      "COMPLETED",
    );
    await producer.getByRole("button", { name: "Clear", exact: true }).click();
    await expect(producer.locator("tbody tr")).toHaveCount(3);
    const routes = [
      [
        admin,
        [
          "admin",
          "admin/users",
          "admin/audit",
          "admin/releases",
          `admin/releases/${releaseId}`,
          "admin/jobs",
          `admin/jobs/${original.split("/").at(-1)}`,
          "admin/dead-letters",
          "admin/workers",
          "admin/queues",
        ],
      ],
      [
        publisher,
        [
          "publisher",
          "publisher/releases",
          `publisher/releases/${releaseId}`,
          "publisher/jobs",
          `publisher/jobs/${original.split("/").at(-1)}`,
        ],
      ],
      [
        producer,
        [
          "producer",
          "producer/submit",
          "producer/jobs",
          `producer/jobs/${original.split("/").at(-1)}`,
          "producer/keys",
          "password",
        ],
      ],
      [
        owner,
        ["worker", "worker/agents", "worker/assignments", "worker/attempts"],
      ],
    ] as const;
    for (const [p, paths] of routes) {
      for (const width of [1440, 390]) {
        await p.setViewportSize({ width, height: 1000 });
        for (const route of paths) {
          await p.goto(`/app/${route}`);
          await expect(p.locator("h1")).toBeVisible();
          await expect(p.locator(".table-skeleton")).toHaveCount(0);
          await expect(p.locator(".error-state")).toHaveCount(0);
          await p.mouse.move(0, 0);
          expect(
            await p.evaluate(
              () => document.documentElement.scrollWidth <= window.innerWidth,
            ),
          ).toBe(true);
          await p.screenshot({
            path: testInfo.outputPath(
              `${route.replaceAll("/", "-")}-${width}.png`,
            ),
            fullPage: true,
          });
        }
        if (width === 390) {
          await p.goto(`/app/${paths[0]}`);
          await p.getByRole("button", { name: "Open navigation" }).click();
          await expect(p.getByLabel("Role", { exact: true })).toBeVisible();
          await p.keyboard.press("Escape");
          await expect(
            p.getByRole("button", { name: "Open navigation" }),
          ).toBeFocused();
        }
      }
    }
    await admin.setViewportSize({ width: 1440, height: 1000 });
    await verifyRequestStates(admin, testInfo);
    await verifyResponsiveStates(admin, testInfo);
    await producer.goto("/app/admin/users");
    await expect(producer).toHaveURL(/\/producer$/);
    // Verify the remaining release and account-management actions on this run's own records.
    await publisher.setViewportSize({ width: 1440, height: 1000 });
    await publisher.goto(`/app/publisher/releases/${releaseId}`);
    await publisher
      .getByLabel("Queue for next version")
      .fill(`reports_v2_${suffix}`);
    await publisher
      .getByRole("button", { name: "Create next version" })
      .click();
    await expect(publisher).not.toHaveURL(new RegExp(releaseId));
    await expect(publisher.locator("h1")).toHaveText(`report_${suffix} · v2`);
    const nextReleaseId = publisher.url().split("/").at(-1)!;
    await publisher.screenshot({
      path: testInfo.outputPath("publisher-draft-upload.png"),
      fullPage: true,
    });
    const examplePromise = publisher.waitForEvent("download");
    await publisher
      .getByRole("link", { name: "Download a ready-to-edit example ZIP" })
      .click();
    const example = await examplePromise;
    await publisher
      .getByLabel("Handler ZIP")
      .setInputFiles((await example.path())!);
    await publisher
      .getByRole("button", { name: "Upload and validate" })
      .click();
    await expect(
      publisher.locator(".status").filter({ hasText: "PENDING APPROVAL" }),
    ).toBeVisible();
    await admin.setViewportSize({ width: 1440, height: 1000 });
    await admin.goto(`/app/admin/releases/${nextReleaseId}`);
    await admin
      .getByLabel("Rejection reason")
      .fill("Acceptance review: verify rejection feedback");
    await admin
      .getByRole("button", { name: "Reject release", exact: true })
      .click();
    await admin.screenshot({
      path: testInfo.outputPath("confirmation.png"),
      fullPage: true,
    });
    await admin
      .getByRole("dialog")
      .getByRole("button", { name: "Reject release", exact: true })
      .click();
    await expect(
      admin.locator(".status").filter({ hasText: /^REJECTED$/ }),
    ).toBeVisible();
    await publisher.reload();
    await expect(
      publisher.locator(".status").filter({ hasText: /^REJECTED$/ }),
    ).toBeVisible();
    await publisher
      .getByRole("button", { name: "Disable release", exact: true })
      .click();
    await publisher
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel", exact: true })
      .click();
    await publisher
      .getByRole("button", { name: "Disable release", exact: true })
      .click();
    await publisher
      .getByRole("dialog")
      .getByRole("button", { name: "Disable release", exact: true })
      .click();
    await expect(
      publisher.locator(".status").filter({ hasText: /^DISABLED$/ }),
    ).toBeVisible();
    await admin.goto("/app/admin/users");
    await expect(
      admin.getByRole("heading", { name: "Accounts", exact: true }),
    ).toBeVisible();
    await expect(admin.locator(".table-skeleton")).toHaveCount(0);
    const account = admin.getByRole("row").filter({ hasText: emails[1] });
    while (!(await account.count())) {
      await expect(
        admin.getByRole("button", { name: "Next", exact: true }),
      ).toBeEnabled();
      await admin.getByRole("button", { name: "Next", exact: true }).click();
      await expect(admin.locator(".table-skeleton")).toHaveCount(0);
    }
    await account.getByRole("button", { name: "Edit", exact: true }).click();
    await admin.getByLabel("Display name").fill(`Updated Producer ${suffix}`);
    await admin
      .getByRole("button", { name: "Save account", exact: true })
      .click();
    await admin
      .getByRole("dialog")
      .getByRole("button", { name: "Save changes", exact: true })
      .click();
    await expect(account).toContainText(`Updated Producer ${suffix}`);
    await account
      .getByRole("button", { name: "Reset password", exact: true })
      .click();
    await admin.getByLabel("New temporary password").fill(temporary);
    await admin
      .getByRole("button", { name: "Reset and revoke access", exact: true })
      .click();
    await admin
      .getByRole("dialog")
      .getByRole("button", { name: "Reset password", exact: true })
      .click();
    await expect(
      admin.getByRole("heading", { name: `Reset password: ${emails[1]}` }),
    ).toHaveCount(0);
    await producer.reload();
    await expect(producer).toHaveURL(/login/);
    await login(producer, emails[1], temporary);
    await replacePassword(producer, temporary, password);
    expect(errors).toEqual([]);
  } finally {
    worker?.kill("SIGTERM");
    await Promise.allSettled(contexts.map((c) => c.close()));
  }
});
