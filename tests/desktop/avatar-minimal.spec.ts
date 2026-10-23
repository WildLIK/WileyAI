import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp, mkdir } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

test("only the fairy and action caption remain; restore controls and persist the view across restart", async () => {
  test.skip(!process.env.WILEYAI_VRM_TEST_PATH, "Requires a local VRM fixture");
  test.setTimeout(90000);
  const data = await mkdtemp(join(tmpdir(), "wiley-minimal-"));
  const launch = () =>
    electron.launch({
      args: ["--mute-audio", "."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  const errors: string[] = [];
  const open = async (page: Page) => {
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("avatar"));
    const avatar = await opened;
    avatar.on("pageerror", (error) => errors.push(error.message));
    await expect(avatar.locator(".avatar-stage")).toHaveAttribute(
      "data-ready",
      "true",
      { timeout: 20000 },
    );
    return avatar;
  };
  try {
    let page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    // Changing the preference before the avatar exists must not hide the app.
    await page.evaluate(() => window.wiley.minimalAvatar(true));
    expect(
      await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows().some((w) => w.isVisible()),
      ),
    ).toBe(true);
    await page.evaluate(() => window.wiley.minimalAvatar(false));
    await page.evaluate(async (path) => {
      const { url, token } = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      };
      const settings = await (
        await fetch(url + "/settings", { headers })
      ).json();
      const response = await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...settings,
          avatar_path: path,
          avatar_fps: 60,
          speak_answers: false,
        }),
      });
      if (!response.ok) throw new Error("Fixture settings failed");
    }, process.env.WILEYAI_VRM_TEST_PATH!);
    await page.reload();
    let avatar = await open(page);
    let stage = avatar.locator(".avatar-stage");
    const normalHeight = (await stage.locator("canvas").boundingBox())!.height;
    await stage
      .getByRole("button", { name: "Статистика 3D", exact: true })
      .click();
    await avatar
      .getByRole("button", { name: "Только фея", exact: true })
      .click();
    const assertMinimal = async () => {
      await expect(avatar.locator(".pet-window")).toHaveAttribute(
        "data-minimal",
        "true",
      );
      for (const selector of [
        ".pet-drag",
        ".pet-actions",
        ".conversation-control",
        ".pet-note",
        ".avatar-view-controls",
        ".avatar-music-status",
        ".avatar-statistics",
      ]) {
        await expect(avatar.locator(selector)).toBeHidden();
      }
      await expect(stage.locator(".avatar-caption")).toBeVisible();
      await expect(stage).toHaveAttribute("data-render", "running");
      await expect
        .poll(async () => (await stage.locator("canvas").boundingBox())!.height)
        .toBeGreaterThan(normalHeight + 50);
      expect(
        await app.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()
            .filter((w) => w.isVisible())
            .map((w) =>
              new URL(w.webContents.getURL()).searchParams.get("view"),
            ),
        ),
      ).toEqual(["avatar"]);
    };
    await assertMinimal();
    await stage.locator("canvas").click({ button: "right" });
    await expect(avatar.locator(".pet-window")).toHaveAttribute(
      "data-minimal",
      "false",
    );
    await expect(avatar.locator(".pet-actions")).toBeVisible();
    await avatar.evaluate(async () => {
      await window.wiley.clickThrough(true);
      await window.wiley.minimalAvatar(true);
    });
    await assertMinimal();
    expect(
      (await avatar.evaluate(() => window.wiley.avatarControls())).clickThrough,
    ).toBe(true);
    // This is the same native action used by the tray and global shortcut,
    // and remains available when the model passes mouse clicks through.
    await avatar.evaluate(() => window.wiley.minimalAvatar(false));
    await expect(avatar.locator(".pet-actions")).toBeVisible();
    await avatar.evaluate(async () => {
      await window.wiley.clickThrough(false);
      await window.wiley.minimalAvatar(true);
    });
    await avatar.reload();
    await expect(stage).toHaveAttribute("data-ready", "true");
    await assertMinimal();
    await mkdir("local/review", { recursive: true });
    await avatar.screenshot({
      path: "local/review/avatar-only-v4.png",
      omitBackground: true,
    });
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await page.waitForFunction(() => Boolean(window.wiley));
    avatar = await open(page);
    stage = avatar.locator(".avatar-stage");
    await assertMinimal();
    await avatar.evaluate(() => window.wiley.minimalAvatar(false));
    await expect(avatar.locator(".pet-actions")).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
