import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";

import { newStudent, signIn, signOut, uploadAndAnalyze, waitForAnalyzed } from "./helpers";

// "Chess LLM": an improvement plan from all analyzed games, at least five of them. Works
// whether or not an LLM is configured in .env (then the plan says it came from a template).

const RUN = Date.now().toString(36);
const PGN = fileURLToPath(new URL("./fixtures/five_games.pgn", import.meta.url));

test("an AI improvement plan needs five analyzed games, and every plan is kept", async ({ page, request }) => {
  test.setTimeout(600_000); // a real LLM can take minutes
  const { coach, student } = await newStudent(request, `llm-${RUN}`, {
    name: `Plan ${RUN}`,
    pgnNames: ["Plan Student"],
  });
  await signIn(page, student);

  // First visit: nothing yet, and the button waits for five analyzed games.
  await page.getByRole("tab", { name: "Chess LLM" }).click();
  const request_ = page.getByTestId("plan-request");
  await expect(page.getByTestId("plan-eligibility")).toContainText("0 of 5 analyzed games");
  await expect(request_.getByRole("button", { name: "Get LLM recommendation" })).toBeDisabled();
  await expect(page.getByText("No plan yet.")).toBeVisible();

  await uploadAndAnalyze(page, PGN, 5);
  await waitForAnalyzed(page, 5, 240_000);

  // Games count once fully analyzed (deeper checks finished): their mistakes are known then.
  await expect(async () => {
    await page.getByRole("tab", { name: "My games" }).click();
    await page.getByRole("tab", { name: "Chess LLM" }).click();
    await expect(page.getByTestId("plan-eligibility")).toContainText("5 analyzed games. Ready.", {
      timeout: 3_000,
    });
  }).toPass({ timeout: 240_000 });
  await request_.getByRole("button", { name: "Get LLM recommendation" }).click();
  // While the coach thinks, the child sees a friendly wait, then the plan.
  const plan = page.getByTestId("plan");
  await expect(plan).toBeVisible({ timeout: 300_000 });

  // Most important first: one mission, on a board from the child's own game.
  const mission = page.getByTestId("mission");
  await expect(mission).toContainText("Your mission");
  await expect(page.getByTestId("mission-move")).toContainText(/In your game against Plan Rival [A-E] you played \S+/);
  await expect(mission.locator("[data-square]").first()).toBeVisible(); // the mini board
  await expect(mission.getByRole("link", { name: "🔍 See it in my game" })).toBeVisible();

  // The training path: tick an activity off; it stays ticked when the child comes back.
  const firstTodo = plan.locator(".todo input[type=checkbox]").first();
  await firstTodo.check();
  await page.reload();
  await expect(page.getByTestId("plan").locator(".todo input[type=checkbox]").first()).toBeChecked();

  // Details for grown-ups are folded away, including what was sent to the AI.
  const more = page.getByTestId("plan").getByText("More for parents and coaches");
  await expect(page.getByTestId("plan-meta")).toBeHidden();
  await more.click();
  await expect(page.getByTestId("plan-meta")).toContainText(/written by .+ and checked against your games|built from a template/);
  await expect(page.getByTestId("plan-meta")).toContainText("5 of 5 analyzed games");
  await expect(page.getByTestId("plan").getByRole("link", { name: /^move \d+/ }).first()).toBeVisible();
  if ((await page.getByTestId("plan-meta").textContent())?.includes("template")) {
    // The template names the repeated missed mate (4.Qe2?? in three games).
    await expect(page.getByTestId("plan")).toContainText("Mating patterns");
  }
  await page.getByTestId("plan").getByText("What was sent to the AI").click();
  await expect(page.getByTestId("plan").locator(".plan-context")).toContainText('"games"');

  // A second request adds to the history; the first is kept.
  await request_.getByRole("button", { name: "Get LLM recommendation" }).click();
  await expect(page.getByText("2 plans saved")).toBeVisible({ timeout: 300_000 });
  await expect(page.getByLabel("Earlier plans").locator("option")).toHaveCount(2);
  await signOut(page);

  // The coach reads the plans, without a button to request one.
  await signIn(page, coach);
  await page.getByRole("link", { name: `Plan ${RUN}` }).click();
  await page.getByRole("tab", { name: "Recommendations" }).click();
  await expect(page.getByRole("heading", { name: "AI improvement plans" })).toBeVisible();
  await expect(page.getByTestId("plan")).toBeVisible();
  await expect(page.getByRole("button", { name: "Get LLM recommendation" })).toHaveCount(0);
});
