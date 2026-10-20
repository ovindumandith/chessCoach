import { expect, type APIRequestContext, type Page } from "@playwright/test";

// Shared e2e setup. Roles: the coach creates the student and their login and then monitors;
// the student adds and analyzes their own games, asks for lessons and solves exercises.

export interface Account {
  email: string;
  password: string;
}

export async function signIn(page: Page, who: Account) {
  await page.goto("/");
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Password").fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

/** A fresh coach (created by the admin from global-setup). */
export async function newCoach(request: APIRequestContext, tag: string): Promise<Account> {
  const coach = { email: `e2e-${tag}@example.org`, password: "e2e-coach-password" };
  const res = await request.post("/api/v1/users", {
    headers: { Authorization: `Bearer ${process.env.E2E_ADMIN_TOKEN}` },
    data: { ...coach, role: "coach" },
  });
  expect(res.status()).toBe(201);
  return coach;
}

/** A fresh coach plus one student with a login, set up through the API. */
export async function newStudent(
  request: APIRequestContext,
  tag: string,
  { name, pgnNames }: { name: string; pgnNames: string[] },
): Promise<{ coach: Account; student: Account; studentId: string }> {
  const coach = await newCoach(request, tag);
  const login = await request.post("/api/v1/auth/login", { data: coach });
  const auth = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const created = await request.post("/api/v1/students", {
    headers: auth,
    data: { display_name: name, aliases: pgnNames },
  });
  expect(created.status()).toBe(201);
  const studentId = (await created.json()).id as string;
  const student = { email: `e2e-${tag}-student@example.org`, password: "e2e-student-password" };
  expect(
    (await request.post(`/api/v1/students/${studentId}/account`, { headers: auth, data: student })).status(),
  ).toBe(201);
  return { coach, student, studentId };
}

/** As the signed-in student: add a PGN in "My games" and analyze everything in it. */
export async function uploadAndAnalyze(page: Page, pgnPath: string, games: number) {
  await page.getByRole("tab", { name: "My games" }).click();
  await page.getByLabel("PGN file").setInputFiles(pgnPath);
  await expect(page.getByText(new RegExp(`Imported\\s*${games}`))).toBeVisible();
  await page.getByRole("button", { name: `Analyze all (${games})` }).click();
}

/** Drag a piece the way a user does (pointer down, move in steps, release). */
export async function drag(page: Page, from: string, to: string) {
  const a = await page.locator(`[data-square="${from}"]`).first().boundingBox();
  const b = await page.locator(`[data-square="${to}"]`).first().boundingBox();
  if (!a || !b) throw new Error("square not found");
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await page.mouse.up();
}
