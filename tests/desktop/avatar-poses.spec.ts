import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createServer } from "node:http";
import { avatarPresets } from "../../src/avatarBehavior";
import { openAvatarTest } from "./avatar-test-helper";

test("fairy poses: real chat cues, shared hover poses and global pointer including click-through", async () => {
  test.skip(
    !process.env.WILEYAI_VRM_TEST_PATH,
    "Requires the local VRM fixture",
  );
  test.setTimeout(90000);
  const server = createServer((req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.method === "GET")
      res.end(JSON.stringify({ models: [{ name: "fixture" }] }));
    else {
      req.resume();
      res.end(
        JSON.stringify({ message: { content: "Хорошо." }, done: true }) + "\n",
      );
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("Fixture port missing");
  const data = await mkdtemp(join(tmpdir(), "wiley-avatar-poses-"));
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
    await page.evaluate(
      async ({ path, port }) => {
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
            model: "fixture",
            base_url: `http://127.0.0.1:${port}`,
            speak_answers: false,
            avatar_motion: true,
            avatar_gaze: true,
            ui_motion: "full",
          }),
        });
        if (!response.ok) throw new Error("Fixture settings failed");
      },
      { path: process.env.WILEYAI_VRM_TEST_PATH!, port: address.port },
    );
    await page.reload();
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    await avatar.setViewportSize({ width: 480, height: 900 });
    const stage = avatar.locator(".avatar-stage");
    await expect(stage).toHaveAttribute("data-ready", "true", {
      timeout: 20000,
    });
    const errors: string[] = [];
    avatar.on("pageerror", (error) => errors.push(error.message));
    // Real frontend sends, with a harmless local model fixture: this exercises
    // reaction routing and tempo without touching the user's model or history.
    for (const preset of avatarPresets.slice(0, 7)) {
      await page.locator("textarea").fill(preset.example);
      await page
        .getByRole("button", { name: "Отправить", exact: true })
        .click();
      await expect(stage).toHaveAttribute("data-pose", preset.gesture);
      await expect(
        page.getByRole("button", { name: "Отправить", exact: true }),
      ).toBeVisible();
    }
    expect(Number(await stage.getAttribute("data-energy"))).toBeGreaterThan(
      0.5,
    );
    const tool = await openAvatarTest(app, page);
    tool.on("pageerror", (error) => errors.push(error.message));
    const panel = tool.getByRole("region", {
      name: "Проверка эмоций и жестов",
      exact: true,
    });
    await panel.getByRole("tab", { name: "Позы феи", exact: true }).click();
    await stage
      .getByRole("button", { name: "Сбросить вид аватара", exact: true })
      .click();
    await mkdir("local/review", { recursive: true });
    for (const preset of avatarPresets) {
      await panel
        .getByRole("button", { name: preset.label, exact: true })
        .click();
      await expect(stage).toHaveAttribute("data-pose", preset.gesture);
      await expect(
        page.locator(".companion-panel .avatar-stage"),
      ).toHaveAttribute("data-pose", preset.gesture);
      await avatar.waitForTimeout(900);
      await stage.locator("canvas").screenshot({
        path: `local/review/avatar-pose-${preset.gesture}.png`,
        omitBackground: true,
      });
      if (
        ["think", "cute", "listen", "tired", "thumbsup"].includes(
          preset.gesture,
        )
      ) {
        const canvas = stage.locator("canvas");
        await canvas.dispatchEvent("wheel", { deltaY: -200 });
        await expect(stage).toHaveAttribute("data-zoom", "1.49");
        await canvas.dispatchEvent("wheel", { deltaY: -150 });
        await expect(stage).toHaveAttribute("data-zoom", "2.01");
        await avatar.waitForTimeout(150);
        await canvas.screenshot({
          path: `local/review/avatar-pose-detail-${preset.gesture}.png`,
          omitBackground: true,
        });
        await stage
          .getByRole("button", { name: "Сбросить вид аватара", exact: true })
          .click();
      }
    }
    await tool.screenshot({
      path: "local/review/avatar-pose-controls.png",
      omitBackground: true,
    });
    await panel.getByRole("button", { name: "Авто", exact: true }).click();
    await stage
      .getByRole("button", { name: "Крупный план лица", exact: true })
      .click();
    // Mock only the test Electron's cursor provider; do not move the real cursor.
    for (const [side, offset] of [
      ["left", -800],
      ["right", 800],
    ] as const) {
      await app.evaluate(({ screen, BrowserWindow }, offset) => {
        const window = BrowserWindow.getAllWindows().find((row) =>
          row.webContents.getURL().includes("view=avatar"),
        )!;
        const bounds = window.getContentBounds();
        screen.getCursorScreenPoint = () => ({
          x: bounds.x + offset,
          y: bounds.y + 300,
        });
      }, offset);
      await expect(stage).toHaveAttribute(
        "data-gaze-x",
        side === "left" ? "-1.00" : "1.00",
      );
      await avatar.waitForTimeout(600);
      await stage.locator("canvas").screenshot({
        path: `local/review/avatar-gaze-${side}.png`,
        omitBackground: true,
      });
    }
    await avatar.evaluate(() => window.wiley.clickThrough(true));
    await app.evaluate(({ screen }) => {
      screen.getCursorScreenPoint = () => ({ x: -20000, y: -20000 });
    });
    await expect(stage).toHaveAttribute("data-gaze-x", "-1.00");
    await expect(stage).toHaveAttribute("data-render", "running");
    await avatar.evaluate(() => window.wiley.clickThrough(false));
    expect(errors).toEqual([]);
    await avatar.close();
    expect(
      await app.evaluate(
        () =>
          (globalThis as typeof globalThis & { avatarErrors: string[] })
            .avatarErrors,
      ),
    ).toEqual([]);
    await writeFile(
      "local/review/avatar-poses-verified.json",
      JSON.stringify(
        avatarPresets.map(({ gesture, example }) => ({ gesture, example })),
        null,
        2,
      ),
    );
  } finally {
    await app.close();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
