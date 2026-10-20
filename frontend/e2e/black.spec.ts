import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

// The student plays BLACK and Black is winning: every evaluation must say so explicitly,
// never as a bare "+" that reads as "White is better".

const RUN = Date.now().toString(36);
const COACH = { email: `e2e-black-${RUN}@example.org`, password: "e2e-coach-password" };
const PGN = fileURLToPath(new URL("./fixtures/black_games.pgn", import.meta.url));

test("evaluations name the side when the student plays Black", async ({ page, request }) => {
  expect(
    (await request.post("/api/v1/users", {
      headers: { Authorization: `Bearer ${process.env.E2E_ADMIN_TOKEN}` },
      data: { ...COACH, role: "coach" },
    })).status(),
  ).toBe(201);

  await page.goto("/");
  await page.getByLabel("Email").fill(COACH.email);
  await page.getByLabel("Password").fill(COACH.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Display name").fill(`Black ${RUN}`);
  await page.getByLabel("PGN player names (comma separated)").fill("Black Student");
  await page.getByRole("button", { name: "Add student" }).click();
  await page.getByRole("link", { name: `Black ${RUN}` }).click();
  await page.locator('input[type="file"]').setInputFiles(PGN);
  await expect(page.getByRole("cell", { name: "black", exact: true })).toBeVisible(); // identified from the PGN name
  await page.getByRole("button", { name: "Analyze all (1)" }).click();
  await page.getByRole("link", { name: "View" }).click();

  const panel = page.getByTestId("move-panel");
  await expect(panel).toContainText("You played Black in this game.");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Black Student you");

  // 3...Nxe5 won White's queen: wait for the analysis, then check the commentary.
  await expect(async () => {
    await page.keyboard.press("Home");
    for (let i = 0; i < 6; i++) await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("verdict")).toHaveText("Best move", { timeout: 3_000 });
  }).toPass({ timeout: 150_000 });
  await expect(panel.getByRole("heading")).toContainText("3… Nxe5");
  await expect(panel).toContainText("you (Black) were winning");
  await expect(panel.locator(".evalnum").last()).toHaveText(/^−\d+\.\d\d$/); // Black better = minus

  // Live engine in the same position (White to move): Black is winning, and it says so.
  const firstLine = page.getByTestId("engine-line").first();
  await expect(firstLine).toContainText(/^−\d+\.\d\d/, { timeout: 60_000 }); // standard notation
  const bar = page.getByRole("meter", { name: "White's share of the winning chances" });
  await expect(async () => expect(Number(await bar.getAttribute("aria-valuenow"))).toBeLessThan(10)).toPass();
  await expect(page.getByText("Black (you)")).toBeVisible();

  // The opponent's blunder one move earlier, from Black's point of view.
  await page.keyboard.press("ArrowUp");
  await expect(panel).toContainText("your opponent's move");
  await expect(panel).toContainText("you (Black)");
  // The opponent's blunder is graded and explained from the board.
  await expect(page.getByTestId("verdict")).toHaveText("Blunder");
  await expect(panel.getByTestId("why")).toContainText("your opponent loses a queen");
  await expect(page.getByRole("navigation", { name: "Key moments" })).toContainText("Opp 3. Qxe5+ ??");
});
