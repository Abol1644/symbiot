import { test, expect, type Page } from "@playwright/test";

/**
 * Symbiote hive-mind mission control E2E.
 *
 * Hard zero-tolerance policy: ANY console error, ANY uncaught page error, or
 * ANY HTTP 5xx response fails the run. The app must boot and degrade
 * gracefully whether or not the Python sidecar is reachable.
 */

async function collectRuntimeFaults(page: Page): Promise<string[]> {
  const faults: string[] = [];
  page.on("pageerror", error => {
    faults.push(`pageerror: ${error.message}`);
  });
  page.on("console", message => {
    if (message.type() === "error") faults.push(`console: ${message.text()}`);
  });
  page.on("response", response => {
    if (response.status() >= 500) faults.push(`http ${response.status()}: ${response.url()}`);
  });
  return faults;
}

test.describe("symbiot mission control", () => {
  test("boots cleanly with Venom shell, branding, and navigation", async ({ page }) => {
    const faults = await collectRuntimeFaults(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Feed the hive a mission." })).toBeVisible();
    await expect(page.locator(".brand-lockup strong")).toHaveText("symbiot");
    await expect(page.locator(".brand-mark svg.crest")).toBeVisible();
    for (const label of ["Run console", "Escalation center", "Providers", "Run history", "Profile"]) {
      await expect(page.getByRole("navigation").getByRole("button", { name: label })).toBeVisible();
    }
    await expect(page.locator(".top-status")).toBeVisible();
    expect(faults, `runtime faults on boot: ${faults.join("\n")}`).toEqual([]);
  });

  test("navigates every main view without errors", async ({ page }) => {
    const faults = await collectRuntimeFaults(page);
    await page.goto("/");
    const nav = page.getByRole("navigation");

    await nav.getByRole("button", { name: "Escalation center" }).click();
    await expect(page.getByText("No escalation in flight")).toBeVisible();

    await nav.getByRole("button", { name: "Providers" }).click();
    await expect(page.getByRole("heading", { name: "Providers" })).toBeVisible();
    await expect(
      page.getByText("Connection roster").or(page.getByText("Provider service unavailable")),
    ).toBeVisible();

    await nav.getByRole("button", { name: "Run history" }).click();
    await expect(page.getByRole("heading", { name: "Run history" })).toBeVisible();

    await nav.getByRole("button", { name: "Profile" }).click();
    await expect(page.getByRole("heading", { name: "Profile" })).toBeVisible();

    await nav.getByRole("button", { name: "Run console" }).click();
    await expect(page.getByRole("heading", { name: "Feed the hive a mission." })).toBeVisible();

    expect(faults, `runtime faults while navigating: ${faults.join("\n")}`).toEqual([]);
  });

  test("command palette opens, filters, and executes", async ({ page }) => {
    const faults = await collectRuntimeFaults(page);
    await page.goto("/");
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
    await page.getByPlaceholder("Jump to a mission action...").fill("providers");
    await expect(page.getByRole("button", { name: /Open Providers/ })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Providers" })).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Command palette" })).toBeHidden();
    expect(faults, `runtime faults in command palette: ${faults.join("\n")}`).toEqual([]);
  });

  test("hive graph renders the agent pipeline nodes", async ({ page }) => {
    const faults = await collectRuntimeFaults(page);
    await page.goto("/");
    const graph = page.locator(".hive-graph .react-flow");
    await expect(graph).toBeVisible();
    for (const node of ["Validator", "Base", "Planner", "Programmer", "Tester"]) {
      await expect(page.getByTestId(`hive-node-${node.toLowerCase()}`)).toBeVisible();
    }
    expect(faults, `runtime faults in hive graph: ${faults.join("\n")}`).toEqual([]);
  });

  test("launching a mission is handled gracefully by the sidecar layer", async ({ page }) => {
    const faults = await collectRuntimeFaults(page);
    await page.goto("/");
    await page.getByRole("button", { name: /Launch mission/ }).click();
    await expect(
      page.getByText("Run service unreachable").or(page.locator(".top-running, .top-done, .top-error")),
    ).toBeVisible({ timeout: 30_000 });
    expect(faults, `runtime faults on mission launch: ${faults.join("\n")}`).toEqual([]);
  });
});
