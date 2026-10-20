import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

// One continuous coach -> student journey through the real UI, real API, real worker.
// The admin token comes from global-setup.ts; everything else is created fresh per run.

const RUN = Date.now().toString(36);
const COACH = { email: `e2e-coach-${RUN}@example.org`, password: "e2e-coach-password" };
const STUDENT = { email: `e2e-student-${RUN}@example.org`, password: "e2e-student-password" };
const PGN = fileURLToPath(new URL("./fixtures/e2e_games.pgn", import.meta.url));

async function signIn(page: Page, email: string, password: string) {
  await page.goto("/");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

/** Drag a piece the way a user does (pointer down, move in steps, release). */
async function drag(page: Page, from: string, to: string) {
  const a = await page.locator(`[data-square="${from}"]`).first().boundingBox();
  const b = await page.locator(`[data-square="${to}"]`).first().boundingBox();
  if (!a || !b) throw new Error("square not found");
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await page.mouse.up();
}

test("coach imports and reviews; student solves an exercise from their own game", async ({ page, request }) => {
  // Setup through the API: an admin creates a fresh coach for this run.
  const created = await request.post("/api/v1/users", {
    headers: { Authorization: `Bearer ${process.env.E2E_ADMIN_TOKEN}` },
    data: { ...COACH, role: "coach" },
  });
  expect(created.status()).toBe(201);

  // --- Coach: create a student and import games -------------------------------------
  await signIn(page, COACH.email, COACH.password);
  await page.getByLabel("Display name").fill(`E2E ${RUN}`);
  await page.getByLabel("PGN player names (comma separated)").fill("E2E Student");
  await page.getByRole("button", { name: "Add student" }).click();
  await page.getByRole("link", { name: `E2E ${RUN}` }).click();

  await page.locator('input[type="file"]').setInputFiles(PGN);
  await expect(page.getByText(/Imported\s*2/)).toBeVisible();
  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await page.getByRole("button", { name: "Analyze all (2)" }).click();

  // --- Coach: the list follows the real Stockfish worker by itself (no reload) -------
  await expect(page.getByText(/Stockfish is working on/)).toBeVisible();
  await expect(page.locator("tbody tr").filter({ hasText: /analyzed|deeper check/ })).toHaveCount(2, {
    timeout: 150_000,
  });
  await page.getByRole("row", { name: /Opponent One/ }).getByRole("link", { name: "View" }).click();
  await expect(page.getByRole("region", { name: "Moves" })).toContainText("Qe2");
  await expect(page.getByRole("navigation", { name: "Key moments" })).toBeVisible();
  // N walks the key moments of BOTH sides in order: 3.Qh5?! (you), 3...Nf6?? (opponent),
  // then the missed mate 4.Qe2??, each with a reason.
  const heading = page.getByTestId("move-panel").getByRole("heading");
  await page.keyboard.press("n");
  await expect(heading).toContainText("3. Qh5");
  await expect(page.getByTestId("verdict")).toHaveText("Inaccuracy");
  await page.keyboard.press("n");
  await expect(heading).toContainText("3… Nf6");
  await expect(heading).toContainText("your opponent's move");
  await page.keyboard.press("n");
  await expect(heading).toContainText("4. Qe2");
  await expect(page.getByTestId("verdict")).toHaveText("Missed a forced mate");
  await expect(page.getByTestId("why")).toContainText("Qxf7# would have forced mate in 1");
  await page.goBack();

  // --- Coach: review findings and confirm one ----------------------------------------
  await page.getByRole("tab", { name: "Review findings" }).click();
  await expect(async () => {
    await page.getByRole("tab", { name: "Profile" }).click();
    await page.getByRole("tab", { name: "Review findings" }).click();
    await expect(page.getByText("Mating patterns").first()).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 90_000 });
  const card = page.locator("article.weakness").filter({ hasText: "Mating patterns" }).first();
  await expect(card.locator("[data-square]").first()).toBeVisible(); // the board renders
  await card.getByRole("button", { name: "Confirm" }).click();

  // --- Coach: profile, lesson, student login ------------------------------------------
  await page.getByRole("tab", { name: "Profile" }).click();
  await page.getByRole("button", { name: "Rebuild profile" }).click();
  await expect(page.getByRole("cell", { name: /Mating patterns/ })).toBeVisible();

  await page.getByRole("tab", { name: "Lessons" }).click();
  await page.getByRole("button", { name: "New lesson" }).click();
  await expect(page.getByRole("heading", { name: /mating patterns/i })).toBeVisible();
  await expect(page.getByText("Your turn:")).toBeVisible();

  await page.getByRole("tab", { name: "Account" }).click();
  await page.getByLabel("Email").fill(STUDENT.email);
  await page.getByLabel("Initial password (10+ characters)").fill(STUDENT.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText(`Account created for ${STUDENT.email}`)).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();

  // --- Student: create exercises and solve one by dragging the queen --------------------
  await signIn(page, STUDENT.email, STUDENT.password);
  await expect(page.getByRole("heading", { name: "Your training" })).toBeVisible();
  await page.getByRole("button", { name: "New exercises for the top priority" }).click();
  await page.getByRole("link", { name: "Solve" }).first().click();
  await expect(page.getByRole("heading", { name: "White to move. Find the best move." })).toBeVisible();

  await page.getByRole("button", { name: /Hint/ }).click();
  await expect(page.getByText("There is a forced checkmate.")).toBeVisible();

  // An illegal drag snaps back and is never sent to the server.
  await drag(page, "h5", "h8");
  await expect(page.getByText("Your moves:")).toHaveCount(0);

  await drag(page, "h5", "f7");
  await expect(page.getByText("Correct!")).toBeVisible();
  await expect(page.getByText(/Solution:\s*Qxf7#/)).toBeVisible();

  // The student cannot reach coach pages.
  await page.goto("/students");
  await expect(page.getByRole("heading", { name: "Your training" })).toBeVisible();
});
