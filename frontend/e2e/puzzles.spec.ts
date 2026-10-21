import { expect, test, type Page } from "@playwright/test";
import { Chess } from "chess.js";
import { fileURLToPath } from "node:url";

import { drag, newStudent, signIn, uploadAndAnalyze } from "./helpers";

// Lichess puzzles for a mistake, getting harder, against the real library loaded with
// `python -m chesscoach.puzzles.load`. Real puzzles are chosen from the live library, so
// the test does not know their solutions: it plays a legal move through the board and
// accepts either verdict. The solving rules themselves are pinned by tests/integration.

const RUN = Date.now().toString(36);
const PGN = fileURLToPath(new URL("./fixtures/repeat_games.pgn", import.meta.url));

async function currentFen(page: Page, setId: string): Promise<{ fen: string; id: string }> {
  return page.evaluate(async (id) => {
    const res = await fetch(`/api/v1/puzzle-sets/${id}`, {
      headers: { Authorization: `Bearer ${sessionStorage.getItem("chesscoach.token")}` },
    });
    const set = await res.json();
    const open = set.puzzles.find((p: { status: string }) => p.status === "open");
    return { fen: open.fen, id: open.id };
  }, setId);
}

test("four puzzles per mistake, each harder, solved on the board", async ({ page, request }) => {
  const { student } = await newStudent(request, `puzzles-${RUN}`, {
    name: `Puzzles ${RUN}`,
    pgnNames: ["Repeat Student"],
  });
  await signIn(page, student);
  await uploadAndAnalyze(page, PGN, 3);
  await expect(page.locator("tbody tr").filter({ hasText: /analyzed|deeper check/ })).toHaveCount(3, {
    timeout: 150_000,
  });

  // The missed mate 4.Qe2 vs Alice -> "Puzzles like this".
  const alice = page.getByTestId("game-mistakes").filter({ has: page.getByRole("heading", { name: /Alice/ }) });
  const qe2 = alice.getByTestId("mistake").filter({ hasText: "4. Qe2" });
  await expect(async () => {
    await page.getByRole("tab", { name: "My games" }).click();
    await page.getByRole("tab", { name: "My mistakes" }).click();
    await expect(qe2).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 90_000 });
  await qe2.getByRole("button", { name: "Puzzles like this" }).click();

  await expect(page.getByRole("heading", { name: /Puzzles: Tactical awareness: Mating patterns/ })).toBeVisible();
  await expect(page.getByText("For your mistake")).toContainText("4. Qe2 vs Alice");
  const steps = page.getByRole("navigation", { name: "Puzzles in this set" }).locator(".puzzle-step");
  await expect(steps).toHaveCount(4);
  const ratings = (await steps.locator(".step-rating").allTextContents()).map(Number);
  expect(ratings).toEqual([...ratings].sort((a, b) => a - b)); // harder each time
  expect(new Set(ratings).size).toBe(4);
  const setId = page.url().split("/puzzles/")[1];
  const panel = page.getByTestId("puzzle-panel");
  await expect(panel.getByRole("heading")).toHaveText(/^(White|Black) to move$/);

  // Play a legal move on the board: the server judges it against the Lichess solution.
  const { fen } = await currentFen(page, setId);
  const legal = new Chess(fen).moves({ verbose: true })[0];
  await expect(page.locator(`[data-square="${legal.from}"] [data-piece]`)).toBeVisible();
  await drag(page, legal.from, legal.to);
  await expect(panel.getByRole("status")).toHaveText(/That's not it|Correct, keep going/);

  // Give up on the first puzzle: solution shown, counted as missed, rating goes down.
  if (await panel.getByRole("button", { name: "Show the solution" }).isVisible()) {
    await panel.getByRole("button", { name: "Show the solution" }).click();
  }
  await expect(panel).toContainText("Solution:");
  await expect(page.getByTestId("puzzle-rating")).toContainText("(was 1500)"); // the rating moved
  await expect(panel.getByRole("link", { name: "This puzzle on Lichess" })).toHaveAttribute(
    "href",
    /^https:\/\/lichess\.org\/training\//,
  );
  await panel.getByRole("button", { name: "Next puzzle (harder)" }).click();
  await expect(steps.nth(1)).toHaveAttribute("aria-current", "true");

  // The mistake now links to its puzzle set; the Exercises tab lists it.
  await page.goto("/?tab=mistakes");
  await expect(qe2.getByTestId("puzzle-progress")).toHaveText(/Puzzles [01]\/4 solved/);
  await page.getByRole("tab", { name: "Exercises" }).click();
  await expect(page.getByRole("row", { name: /Mating patterns.*4\. Qe2 vs Alice/ })).toBeVisible();
});
