import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
} from "@playwright/test";
import { mkdtemp, readFile, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openAvatarTest } from "./avatar-test-helper";

async function catchMainErrors(app: ElectronApplication) {
  await app.evaluate(() => {
    const errors: string[] = [];
    (
      globalThis as typeof globalThis & { avatarErrors: string[] }
    ).avatarErrors = errors;
    process.on("uncaughtException", (error) =>
      errors.push(error.stack || error.message),
    );
  });
}

test("fairy window resizes by buttons, keyboard and corner drag, persists across restart and keeps tools beside it", async () => {
  test.skip(
    !process.env.WILEYAI_VRM_TEST_PATH,
    "Requires the local VRM fixture",
  );
  test.setTimeout(90000);
  const data = await mkdtemp(join(tmpdir(), "wiley-avatar-window-"));
  const launch = () =>
    electron.launch({
      args: ["--mute-audio", "."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  try {
    await catchMainErrors(app);
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
        body: JSON.stringify({ ...settings, avatar_path: path }),
      });
      if (!response.ok) throw new Error("Fixture settings failed");
    }, process.env.WILEYAI_VRM_TEST_PATH!);
    await page.reload();
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    const errors: string[] = [];
    avatar.on("pageerror", (error) => errors.push(error.message));
    await expect(avatar.locator(".avatar-stage")).toHaveAttribute(
      "data-ready",
      "true",
      { timeout: 20000 },
    );
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().endsWith("view=avatar"))!
        .setBounds({ x: 24, y: 24, width: 420, height: 640 });
    });
    const size = () => avatar.evaluate(() => window.wiley.avatarSize());
    await expect.poll(async () => (await size()).width).toBe(420);
    await avatar
      .getByRole("button", { name: "Увеличить окно феи", exact: true })
      .click();
    await expect.poll(async () => (await size()).width).toBeGreaterThan(420);
    const bigger = await size();
    const grip = avatar.getByRole("button", {
      name: "Изменить размер окна феи",
      exact: true,
    });
    await grip.focus();
    await grip.press("ArrowRight");
    await expect.poll(async () => (await size()).width).toBe(bigger.width + 32);
    const before = await size();
    const box = (await grip.boundingBox())!;
    await avatar.mouse.move(box.x + 10, box.y + 10);
    await avatar.mouse.down();
    await avatar.mouse.move(box.x + 90, box.y + 70, { steps: 8 });
    await avatar.mouse.up();
    await expect
      .poll(async () => (await size()).width)
      .toBeGreaterThan(before.width + 40);
    await expect
      .poll(async () => (await size()).height)
      .toBeGreaterThan(before.height + 30);
    let resized = await size();
    const height = (await avatar.locator("canvas").boundingBox())!.height;
    const tool = await openAvatarTest(app, page);
    await expect(
      tool.getByRole("button", { name: "Радость", exact: true }),
    ).toBeEnabled();
    expect((await avatar.locator("canvas").boundingBox())!.height).toBe(height);
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().endsWith("view=avatar"))!
        .setPosition(90, 70);
    });
    const geometry = await app.evaluate(({ BrowserWindow }) => {
      const avatar = BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().endsWith("view=avatar"))!
        .getBounds();
      const tool = BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().endsWith("view=avatar-test"))!
        .getBounds();
      return { avatar, tool };
    });
    expect(
      geometry.avatar.x + geometry.avatar.width <= geometry.tool.x ||
        geometry.tool.x + geometry.tool.width <= geometry.avatar.x,
    ).toBe(true);
    await mkdir("local/review", { recursive: true });
    await avatar.screenshot({
      path: "local/review/avatar-window-resized.png",
      omitBackground: true,
    });
    await tool.screenshot({ path: "local/review/avatar-controls-window.png" });
    await tool.close();
    await expect(avatar.locator(".avatar-stage")).toHaveAttribute(
      "data-testing",
      "false",
    );
    resized = await size();
    await expect
      .poll(
        async () =>
          JSON.parse(await readFile(join(data, "avatar-window.json"), "utf8"))
            .width,
      )
      .toBe(resized.width);
    expect(errors).toEqual([]);
    expect(
      await app.evaluate(
        () =>
          (globalThis as typeof globalThis & { avatarErrors: string[] })
            .avatarErrors,
      ),
    ).toEqual([]);
    await app.close();
    app = await launch();
    await catchMainErrors(app);
    const restarted = await app.firstWindow();
    const reopened = app.waitForEvent("window");
    await restarted
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const restored = await reopened;
    await expect(restored.locator(".avatar-stage")).toHaveAttribute(
      "data-ready",
      "true",
      { timeout: 20000 },
    );
    // At 125% scaling Windows may round one DIP to a neighbouring physical pixel.
    const restoredSize = await restored.evaluate(() =>
      window.wiley.avatarSize(),
    );
    expect(Math.abs(restoredSize.width - resized.width)).toBeLessThanOrEqual(1);
    expect(Math.abs(restoredSize.height - resized.height)).toBeLessThanOrEqual(
      1,
    );
    await expect(restored.locator(".avatar-stage")).toHaveAttribute(
      "data-testing",
      "false",
    );
    await writeFile(
      "local/review/avatar-window-geometry.json",
      JSON.stringify(
        {
          resized,
          geometry,
          restored: await restored.evaluate(() => window.wiley.avatarSize()),
        },
        null,
        2,
      ),
    );
  } finally {
    await app.close();
  }
});
