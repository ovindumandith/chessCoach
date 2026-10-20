import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

// Live in-browser engine + "you made the same mistake before" links, against the real stack.

const RUN = Date.now().toString(36);
const COACH = { email: `e2e-analysis-${RUN}@example.org`, password: "e2e-coach-password" };
const PGN = fileURLToPath(new URL("./fixtures/repeat_games.pgn", import.meta.url));

async function drag(page: Page, from: string, to: string) {
  const a = await page.locator(`[data-square="${from}"]`).first().boundingBox();
  const b = await page.locator(`[data-square="${to}"]`).first().boundingBox();
  if (!a || !b) throw new Error("square not found");
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await page.mouse.up();
}

test("live engine and links to the same mistake in earlier games", async ({ page, request }) => {
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
  await page.getByLabel("Display name").fill(`Repeat ${RUN}`);
  await page.getByLabel("PGN player names (comma separated)").fill("Repeat Student");
  await page.getByRole("button", { name: "Add student" }).click();
  await page.getByRole("link", { name: `Repeat ${RUN}` }).click();
  await page.locator('input[type="file"]').setInputFiles(PGN);
  await expect(page.getByText(/Imported\s*3/)).toBeVisible();
  await page.getByRole("button", { name: "Analyze all (3)" }).click();

  // Open the latest game (vs Carol): the same missed mate as against Alice two months earlier.
  await page.getByRole("row", { name: /Carol/ }).getByRole("link", { name: "View" }).click();
  // The original game is viewable straight away; analysis fills in as it completes.
  await expect(page.getByRole("region", { name: "Moves" })).toContainText("Qe2");
  const chip = page.getByRole("navigation", { name: "Key moments" }).getByRole("button", { name: /4\. Qe2/ });
  await expect(async () => {
    await page.reload();
    await expect(chip).toBeVisible({ timeout: 2_000 });
    await expect(page.locator(".movelist .repeat").first()).toBeVisible({ timeout: 2_000 }); // seen before
  }).toPass({ timeout: 150_000 });

  // Keyboard navigation through the original game.
  const panel = page.getByTestId("move-panel");
  await page.keyboard.press("Home");
  await expect(panel).toContainText("Start position");
  for (let i = 0; i < 7; i++) await page.keyboard.press("ArrowDown");
  await expect(panel.getByRole("heading")).toContainText("4. Qe2");
  await expect(page.getByTestId("verdict")).toHaveText("Missed a forced mate");
  await expect(panel).toContainText("Better was Qxf7#");
  await page.keyboard.press("ArrowUp");
  await expect(panel).toContainText("your opponent's move");
  await expect(panel.getByRole("heading")).toContainText("3… Nf6");
  // The opponent's move is annotated too: 3...Nf6?? allowed mate in one.
  await expect(page.getByTestId("verdict")).toHaveText("Allowed a forced mate");
  await expect(panel).toContainText("Your opponent should have played");
  await chip.click(); // jump via the key-moments strip
  await expect(panel.getByRole("heading")).toContainText("4. Qe2");
  await expect(panel.getByTestId("why")).toContainText("Qxf7# would have forced mate in 1");

  const finding = panel.getByTestId("finding").filter({ hasText: "Mating patterns" }).filter({ hasText: "missed" });
  await expect(finding).toContainText("You made the same mistake in 1 other game");
  const link = finding.getByRole("link", { name: /vs Alice, 2024-01-10, move 4: Qe2/ });
  await expect(finding.getByText("(earlier)")).toBeVisible();

  // Live engine one move earlier (after 3...Nf6, White to move): mate in one.
  await page.keyboard.press("ArrowLeft");
  const firstLine = page.getByTestId("engine-line").first();
  await expect(firstLine).toContainText("#1", { timeout: 60_000 });
  await expect(firstLine).toContainText("Qxf7#");

  // Explore: play the mate on the board; Esc returns to the game. Wait until the board has
  // finished animating back to this position (the engine reacts faster than the animation).
  await expect(page.locator('[data-square="h5"] [data-piece="wQ"]')).toBeVisible();
  await drag(page, "h5", "f7");
  await expect(page.getByText("Exploring", { exact: true })).toBeVisible();
  await expect(page.getByText("No legal moves: the game is over in this position.")).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press("Escape");
  await expect(page.getByText("Exploring", { exact: true })).toHaveCount(0);

  // Back to 4.Qe2 and follow the link: the earlier game opens at that exact move.
  await page.keyboard.press("ArrowRight");
  await expect(panel.getByRole("heading")).toContainText("4. Qe2");
  await link.click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Alice");
  await expect(panel.getByRole("heading")).toContainText("4. Qe2");
  const earlierFinding = panel.getByTestId("finding").filter({ hasText: "Mating patterns" }).filter({ hasText: "missed" });
  await expect(earlierFinding.getByRole("link", { name: /vs Carol, 2024-03-10, move 4: Qe2/ })).toBeVisible();
  await expect(earlierFinding.getByText("(later)")).toBeVisible();
});
