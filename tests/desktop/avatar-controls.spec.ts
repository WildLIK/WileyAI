import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openAvatarTest } from "./avatar-test-helper";

test("click-through toggles off through reachable controls, and closing the avatar leaves chat alive", async () => {
  test.skip(
    !process.env.WILEYAI_VRM_TEST_PATH,
    "Requires the local VRM fixture",
  );
  test.setTimeout(60000);
  const data = await mkdtemp(join(tmpdir(), "wiley-avatar-controls-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    await app.evaluate(() => {
      const errors: string[] = [];
      (
        globalThis as typeof globalThis & { avatarErrors: string[] }
      ).avatarErrors = errors;
      process.on("uncaughtException", (error) =>
        errors.push(error.stack || error.message),
      );
    });
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(async (path) => {
      const { url, token } = await window.wiley.connection(),
        headers = {
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
          avatar_gaze: false,
        }),
      });
      if (!response.ok) throw new Error("Fixture settings failed");
    }, process.env.WILEYAI_VRM_TEST_PATH!);
    await page.reload();
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened,
      stage = avatar.locator(".avatar-stage");
    const errors: string[] = [];
    avatar.on("pageerror", (error) => errors.push(error.message));
    await expect(stage).toHaveAttribute("data-ready", "true", {
      timeout: 20000,
    });
    await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find((row) =>
        row.webContents.getURL().endsWith("view=avatar"),
      )!;
      const original = window.setIgnoreMouseEvents.bind(window);
      (
        globalThis as typeof globalThis & { avatarIgnored: boolean }
      ).avatarIgnored = false;
      window.setIgnoreMouseEvents = (value, options) => {
        (
          globalThis as typeof globalThis & { avatarIgnored: boolean }
        ).avatarIgnored = value;
        original(value, options);
      };
    });
    const moveCursor = async (point: { x: number; y: number }) => {
      await app.evaluate(({ BrowserWindow, screen }, point) => {
        const bounds = BrowserWindow.getAllWindows()
          .find((row) => row.webContents.getURL().endsWith("view=avatar"))!
          .getContentBounds();
        screen.getCursorScreenPoint = () => ({
          x: bounds.x + point.x,
          y: bounds.y + point.y,
        });
      }, point);
    };
    const ignored = () =>
      app.evaluate(
        () =>
          (globalThis as typeof globalThis & { avatarIgnored: boolean })
            .avatarIgnored,
      );
    const button = avatar.getByRole("button", {
      name: "Пропуск кликов",
      exact: true,
    });
    for (let i = 0; i < 3; i++) {
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
      const body = (await stage.locator("canvas").boundingBox())!;
      await moveCursor({
        x: body.x + body.width / 2,
        y: body.y + body.height / 2,
      });
      await expect.poll(ignored).toBe(true);
      const toolbar = (await button.boundingBox())!;
      await moveCursor({
        x: toolbar.x + toolbar.width / 2,
        y: toolbar.y + toolbar.height / 2,
      });
      await expect.poll(ignored).toBe(false);
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "false");
      await expect.poll(ignored).toBe(false);
    }
    const tool = await openAvatarTest(app, page);
    await expect(stage).toHaveAttribute("data-testing", "true");
    await button.click();
    const close = avatar.getByRole("button", {
      name: "Закрыть окно аватара",
      exact: true,
    });
    const box = (await close.boundingBox())!;
    await moveCursor({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
    await expect.poll(ignored).toBe(false);
    await close.click();
    await expect.poll(() => tool.isClosed()).toBe(true);
    await expect
      .poll(() => avatar.evaluate(() => window.wiley.avatarControls()))
      .toEqual({ visible: false, clickThrough: false });
    await expect(page.locator("textarea")).toBeVisible();
    expect(page.isClosed()).toBe(false);
    await page.evaluate(() => window.wiley.showWindow("avatar"));
    await expect
      .poll(() => avatar.evaluate(() => window.wiley.avatarControls()))
      .toEqual({ visible: true, clickThrough: false });
    await expect(button).toHaveAttribute("aria-pressed", "false");
    await expect(stage).toHaveAttribute("data-testing", "false");
    await expect(stage).toHaveAttribute("data-render", "running");
    expect(errors).toEqual([]);
    expect(
      await app.evaluate(
        () =>
          (globalThis as typeof globalThis & { avatarErrors: string[] })
            .avatarErrors,
      ),
    ).toEqual([]);
  } finally {
    await app.close();
  }
});
