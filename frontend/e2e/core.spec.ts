import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

import { drag, newCoach, signIn, signOut, uploadAndAnalyze, waitForAnalyzed } from "./helpers";

// One continuous journey through the real UI, real API and real worker:
// the coach onboards a student; the student adds and analyzes games, acknowledges a mistake,
// gets the AI coach's recommendation and solves an exercise from their own mistake; the coach
// monitors activity, the student's mistakes and recommendations, and mistakes across students.

const RUN = Date.now().toString(36);
const STUDENT = { email: `e2e-student-${RUN}@example.org`, password: "e2e-student-password" };
const PGN = fileURLToPath(new URL("./fixtures/e2e_games.pgn", import.meta.url));
const OWN_PGN = fileURLToPath(new URL("./fixtures/student_upload.pgn", import.meta.url));

test("student analyzes, acknowledges and trains on their own games; the coach monitors", async ({
  page,
  request,
}) => {
  const coach = await newCoach(request, `coach-${RUN}`);

  // --- Coach: create the student and their login ----------------------------------------
  await signIn(page, coach);
  await page.getByLabel("Display name").fill(`E2E ${RUN}`);
  await page.getByLabel("PGN player names (comma separated)").fill("E2E Student");
  await page.getByRole("button", { name: "Add student" }).click();
  await page.getByRole("link", { name: `E2E ${RUN}` }).click();
  // Coaches monitor: no upload, and no Exercises tab.
  await expect(page.getByText("Your student has not added any games yet.")).toBeVisible();
  await expect(page.getByLabel("PGN file")).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Exercises" })).toHaveCount(0);
  await page.getByRole("tab", { name: "Account" }).click();
  await page.getByLabel("Email").fill(STUDENT.email);
  await page.getByLabel("Initial password (10+ characters)").fill(STUDENT.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText(`Account created for ${STUDENT.email}`)).toBeVisible();
  await signOut(page);

  // --- Student: add games and analyze them; the list follows the worker by itself -------
  await signIn(page, STUDENT);
  await expect(page.getByRole("navigation", { name: "Coach" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Getting started" })).toBeVisible();
  await uploadAndAnalyze(page, PGN, 2);
  await expect(page.getByText(/Stockfish is working on/)).toBeVisible();
  await waitForAnalyzed(page, 2, 150_000);

  // --- Student: step through a game; N walks the key moments of both sides --------------
  await page.getByRole("row", { name: /Opponent One/ }).getByRole("link", { name: "View" }).click();
  await expect(page.getByRole("region", { name: "Moves" })).toContainText("Qe2");
  const heading = page.getByTestId("move-panel").getByRole("heading");
  await expect(async () => {
    await page.reload(); // findings land a moment after the analysis
    await expect(page.getByRole("navigation", { name: "Key moments" })).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 60_000 });
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

  // --- Student: mistakes game by game; acknowledge one ------------------------------------
  const card = (opponent: string) =>
    page.getByTestId("game-mistakes").filter({ has: page.getByRole("heading", { name: new RegExp(opponent) }) });
  const game = card("Opponent One");
  await expect(async () => {
    await page.getByRole("tab", { name: "My games" }).click();
    await page.getByRole("tab", { name: "My mistakes" }).click();
    await expect(game.getByTestId("mistake").filter({ hasText: "4. Qe2" })).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 60_000 });
  const qe2 = game.getByTestId("mistake").filter({ hasText: "4. Qe2" });
  await expect(qe2).toContainText("Better was Qxf7#");
  await expect(qe2).toContainText("Mating patterns");
  // In the second game 3.Qh5 was an inaccuracy, but the mate 4.Qxf7# is no mistake.
  await expect(card("Opponent Two").getByTestId("mistake").filter({ hasText: "3. Qh5" })).toBeVisible();
  await expect(card("Opponent Two").getByTestId("mistake").filter({ hasText: "Qxf7#" })).toHaveCount(0);
  await qe2.getByRole("button", { name: "Acknowledge" }).click();
  await expect(qe2).toContainText(/acknowledged \d{4}-\d\d-\d\d/);
  await expect(page.getByRole("button", { name: "Confirm" })).toHaveCount(0); // nobody reviews findings

  // --- Student: the AI coach's recommendation, then an exercise from their own game ------
  await page.getByRole("tab", { name: "Exercises" }).click();
  const rec = page.getByTestId("recommendation");
  await rec.getByRole("button", { name: "Get a recommendation" }).click();
  await expect(rec.getByRole("heading", { name: /mating patterns/i })).toBeVisible();
  await expect(rec.getByText("Your turn:")).toBeVisible();
  await expect(rec.getByText("Practice", { exact: true })).toBeVisible(); // the recommended exercises
  await rec.getByRole("button", { name: /Practise this/ }).click();
  await expect(page.getByText("For this recommendation")).toBeVisible();
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

  // --- Student: more games, including a guest-account one they claim ---------------------
  await page.goto("/?tab=games");
  await page.getByLabel("PGN file").setInputFiles(OWN_PGN);
  await expect(page.getByText(/Imported\s*1\s*· need confirmation\s*1/)).toBeVisible();
  const own = page.getByRole("row", { name: /E2E Student.*Online Rival/ });
  await expect(own.getByText("you", { exact: true })).toBeVisible();
  const guest = page.getByRole("row", { name: /guest_4821/ });
  await guest.getByRole("button", { name: "white" }).click();
  await expect(guest).toContainText("white");
  await own.getByRole("button", { name: "Analyze" }).click();
  await expect(own).toContainText(/queued|analyzing|analyzed|deeper check/);

  // The student cannot reach coach pages.
  await page.goto("/mistakes");
  await expect(page.getByRole("heading", { name: "Your training" })).toBeVisible();
  await signOut(page);

  // --- Coach: monitors activity, mistakes and recommendations (read-only) -----------------
  await signIn(page, coach);
  const row = page.getByRole("row", { name: new RegExp(`E2E ${RUN}`) });
  await expect(row.getByRole("cell").nth(3)).toHaveText("4"); // games in total
  await expect(row.getByRole("cell").nth(4)).toContainText(/^4\s*latest \d{4}-\d\d-\d\d/); // all by the student
  await expect(row.getByRole("cell").nth(5)).toContainText(/^\d+ of \d+$/); // open mistakes
  await expect(row.getByRole("cell").nth(6)).toHaveText("yes");

  // Mistakes across students.
  await page.getByRole("link", { name: "Mistakes across students" }).click();
  const mate = page.getByRole("row", { name: /Mating patterns/ });
  await expect(mate).toContainText(`E2E ${RUN}`);
  await expect(mate).toContainText("1 acknowledged");
  await expect(mate.getByRole("link", { name: /4\. Qe2/ }).first()).toBeVisible();

  await page.getByRole("link", { name: "Students", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Students", exact: true })).toBeVisible();
  await row.getByRole("link", { name: `E2E ${RUN}` }).click();
  await expect(page.getByTestId("student-added")).toContainText("4 of 4 games were added by the student");
  await expect(page.getByRole("button", { name: /Analyze/ })).toHaveCount(0); // read-only for the coach
  await expect(page.getByRole("tab", { name: "Review findings" })).toHaveCount(0);

  await page.getByRole("tab", { name: "Mistakes" }).click();
  const coachQe2 = card("Opponent One")
    .getByTestId("mistake")
    .filter({ hasText: "4. Qe2" });
  await expect(coachQe2).toContainText(/acknowledged \d{4}-\d\d-\d\d/); // what the student acknowledged
  await expect(page.getByRole("button", { name: "Acknowledge" })).toHaveCount(0);

  await page.getByRole("tab", { name: "Profile" }).click();
  await expect(page.getByRole("cell", { name: /Mating patterns/ })).toBeVisible(); // built automatically
  await expect(page.getByRole("button", { name: "Rebuild profile" })).toHaveCount(0);

  await page.getByRole("tab", { name: "Recommendations" }).click();
  await expect(page.getByRole("button", { name: /recommendation/i })).toHaveCount(0);
  await expect(page.getByTestId("lesson-meta")).toContainText(/validation\s*(valid|fallback)/);
  await expect(page.getByRole("heading", { name: /mating patterns/i })).toBeVisible(); // in full
});
