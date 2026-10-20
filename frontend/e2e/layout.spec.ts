import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

import { newStudent, signIn, uploadAndAnalyze } from "./helpers";

// The game workspace must fit on one screen: board, navigation, live engine and this move's
// verdict all visible at a glance, and stepping with the keyboard never scrolls the page.
// Set LAYOUT_SHOTS=<dir> to also save a screenshot per viewport.

const RUN = Date.now().toString(36);
const PGN = fileURLToPath(new URL("./fixtures/black_games.pgn", import.meta.url));
const VIEWPORTS = [
  { width: 1366, height: 768 },
  { width: 1536, height: 864 },
  { width: 1920, height: 1080 },
];

async function box(page: Page, selector: string) {
  const b = await page.locator(selector).first().boundingBox();
  if (!b) throw new Error(`${selector} is not rendered`);
  return b;
}

test("the game workspace fits the screen and keyboard navigation never scrolls the page", async ({
  page,
  request,
}) => {
  const { student } = await newStudent(request, `layout-${RUN}`, {
    name: `Layout ${RUN}`,
    pgnNames: ["Black Student"],
  });
  await signIn(page, student);
  await uploadAndAnalyze(page, PGN, 1);
  await page.getByRole("link", { name: "View" }).click();
  await expect(page.getByRole("navigation", { name: "Key moments" })).toBeVisible({ timeout: 150_000 });

  for (const vp of VIEWPORTS) {
    await page.setViewportSize(vp);
    await page.keyboard.press("Home");
    for (let i = 0; i < 6; i++) await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("engine-line").first()).toBeVisible({ timeout: 60_000 });

    expect(await page.evaluate(() => window.scrollY), `page scrolled at ${vp.width}x${vp.height}`).toBe(0);
    const board = await box(page, ".board");
    const nav = await box(page, ".nav-buttons");
    const engine = await box(page, "section.engine");
    const panel = await box(page, '[data-testid="move-panel"]');
    const where = `${vp.width}x${vp.height}`;
    expect(board.y + board.height, `board cut off at ${where}`).toBeLessThanOrEqual(vp.height);
    expect(nav.y + nav.height, `navigation cut off at ${where}`).toBeLessThanOrEqual(vp.height);
    expect(engine.y + engine.height, `engine cut off at ${where}`).toBeLessThanOrEqual(vp.height);
    expect(panel.y + Math.min(panel.height, 120), `verdict cut off at ${where}`).toBeLessThanOrEqual(vp.height);
    expect(board.width, `board too small at ${where}`).toBeGreaterThanOrEqual(420);

    if (process.env.LAYOUT_SHOTS) await page.screenshot({ path: `${process.env.LAYOUT_SHOTS}/layout-${where}.png` });
  }
});
