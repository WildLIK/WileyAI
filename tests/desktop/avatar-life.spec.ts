import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { wav } from "../../src/voice/speech";

async function configure(page: Page, path: string) {
  await page.evaluate(async (path) => {
    const { url, token } = await window.wiley.connection();
    const headers = {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json",
    };
    const settings = await (await fetch(url + "/settings", { headers })).json();
    const response = await fetch(url + "/settings", {
      method: "PUT",
      headers,
      body: JSON.stringify({
        ...settings,
        avatar_path: path,
        avatar_motion: true,
        avatar_gaze: true,
        avatar_expressions: true,
        avatar_fps: 30,
        ui_motion: "full",
        tts_engine: "sapi",
        speak_answers: true,
      }),
    });
    if (!response.ok) throw new Error("Fixture settings failed");
  }, path);
}

test("living VRM: zoom, shared turn, real playback, hidden window, sleep and display recovery", async () => {
  test.skip(
    !process.env.WILEYAI_VRM_TEST_PATH,
    "Requires an embedded local VRM fixture",
  );
  test.setTimeout(90000);
  const data = await mkdtemp(join(tmpdir(), "wiley-avatar-life-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await configure(page, process.env.WILEYAI_VRM_TEST_PATH!);
    await page.reload();
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    avatar.on("pageerror", (error) => errors.push(error.message));
    await avatar.setViewportSize({ width: 460, height: 740 });
    const stage = avatar.locator(".avatar-stage");
    await expect(stage).toHaveAttribute("data-ready", "true", {
      timeout: 20000,
    });
    await expect(stage).toHaveAttribute("data-render", "running");
    await stage
      .getByRole("button", { name: "Статистика 3D", exact: true })
      .click();
    await expect(stage.locator("output")).toContainText("FPS");
    await mkdir("local/review", { recursive: true });
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().includes("view=chat"))!
        .hide();
    });
    await expect(
      page.locator(".companion-panel .avatar-stage"),
    ).toHaveAttribute("data-render", "paused");
    await avatar.waitForTimeout(1300);
    await writeFile(
      "local/review/avatar-metrics.json",
      JSON.stringify(
        {
          statistics: await stage.locator("output").textContent(),
          renderer: await stage.locator("output").getAttribute("title"),
        },
        null,
        2,
      ),
    );
    await avatar.screenshot({
      path: "local/review/avatar-alive-full.png",
      omitBackground: true,
    });
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().includes("view=chat"))!
        .show();
    });
    await stage.locator("canvas").hover();
    await avatar.mouse.wheel(0, -180);
    await expect
      .poll(async () => Number(await stage.getAttribute("data-zoom")))
      .toBeGreaterThan(1);
    for (let i = 0; i < 3; i++)
      await stage
        .getByRole("button", { name: "Приблизить аватара", exact: true })
        .click();
    const zoom = await stage.getAttribute("data-zoom");
    await expect
      .poll(async () => Number(await stage.getAttribute("data-render-frames")))
      .toBeGreaterThan(15);
    await avatar.screenshot({
      path: "local/review/avatar-alive-closeup.png",
      omitBackground: true,
    });
    await avatar.reload();
    await expect(stage).toHaveAttribute("data-ready", "true", {
      timeout: 20000,
    });
    await expect(stage).toHaveAttribute("data-zoom", zoom!);
    await expect(stage.locator("canvas")).toHaveCount(1);
    await stage
      .getByRole("button", { name: "Сбросить вид аватара", exact: true })
      .click();
    // A slow synthesizer must not move the mouth before the media element plays.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/voice/synthesize", async (route) => {
      await gate;
      await route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(16000 * 5), 16000)),
      });
    });
    await page.route("**/chat", (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: [
          { type: "delta", text: "Привет! Рада помочь." },
          {
            type: "done",
            message: {
              id: "avatar-turn",
              role: "assistant",
              content: "Привет! Рада помочь.",
              created: new Date().toISOString(),
            },
          },
        ]
          .map((event) => "data: " + JSON.stringify(event) + "\n\n")
          .join(""),
      }),
    );
    await page.getByLabel("Сообщение", { exact: true }).fill("Привет!");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(stage).toHaveAttribute("data-phase", "thinking");
    await expect(stage).toHaveAttribute("data-mouth", "closed");
    await expect(stage).toHaveAttribute("data-emotion", "happy");
    await avatar.waitForTimeout(1200);
    await avatar.screenshot({
      path: "local/review/avatar-alive-greeting.png",
      omitBackground: true,
    });
    release();
    await expect(stage).toHaveAttribute("data-phase", "speaking");
    await expect(stage).toHaveAttribute("data-mouth", "active");
    await avatar.keyboard.press("Escape");
    await expect(stage).toHaveAttribute("data-phase", "idle");
    await expect(stage).toHaveAttribute("data-mouth", "closed");
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().includes("view=avatar"))!
        .hide();
    });
    await expect(stage).toHaveAttribute("data-render", "paused");
    const hiddenFrames = await stage.getAttribute("data-render-frames");
    await avatar.waitForTimeout(350);
    expect(await stage.getAttribute("data-render-frames")).toBe(hiddenFrames);
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()
        .find((w) => w.webContents.getURL().includes("view=avatar"))!
        .show();
    });
    await expect(stage).toHaveAttribute("data-render", "running");
    // Emit lifecycle notifications in this isolated Electron process; do not suspend Windows.
    await avatar.evaluate(async () => {
      const lease = await window.wiley.acquireConversation();
      await window.wiley.updateConversation(lease, "listening");
    });
    expect(
      (await avatar.evaluate(() => window.wiley.conversationState())).active,
    ).toBe(true);
    await app.evaluate(({ powerMonitor }) => {
      powerMonitor.emit("suspend");
    });
    await expect(stage).toHaveAttribute("data-render", "paused");
    const sleepingFrames = await stage.getAttribute("data-render-frames");
    await avatar.waitForTimeout(350);
    expect(await stage.getAttribute("data-render-frames")).toBe(sleepingFrames);
    await app.evaluate(({ powerMonitor }) => {
      powerMonitor.emit("resume");
    });
    await expect(stage).toHaveAttribute("data-render", "running");
    expect(
      (await avatar.evaluate(() => window.wiley.conversationState())).active,
    ).toBe(false);
    await avatar
      .getByRole("button", {
        name: "Переместить аватара на другой экран",
        exact: true,
      })
      .click();
    await app.evaluate(({ BrowserWindow, screen }) => {
      const window = BrowserWindow.getAllWindows().find((w) =>
        w.webContents.getURL().includes("view=avatar"),
      )!;
      window.setPosition(30000, 30000);
      screen.emit("display-removed", {}, screen.getPrimaryDisplay());
    });
    await expect
      .poll(async () =>
        app.evaluate(({ BrowserWindow, screen }) => {
          const window = BrowserWindow.getAllWindows().find((w) =>
            w.webContents.getURL().includes("view=avatar"),
          )!;
          const bounds = window.getBounds(),
            area = screen.getDisplayMatching(bounds).workArea;
          return bounds.x >= area.x &&
            bounds.y >= area.y &&
            bounds.x + bounds.width <= area.x + area.width &&
            bounds.y + bounds.height <= area.y + area.height
            ? "visible"
            : JSON.stringify({ bounds, area });
        }),
      )
      .toBe("visible");
    await expect(stage).toHaveAttribute("data-render", "running");
    await stage
      .getByRole("button", { name: "Сбросить вид аватара", exact: true })
      .click();
    await expect(stage).toHaveAttribute("data-zoom", "1.00");
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Аватар", exact: true }).click();
    await page
      .getByLabel("Частота кадров аватара", { exact: true })
      .selectOption("15");
    await page
      .getByLabel("Дыхание, движения в покое и жесты", { exact: true })
      .uncheck();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(stage).toHaveAttribute("data-target-fps", "15");
    await stage
      .getByRole("button", { name: "Статистика 3D", exact: true })
      .click();
    await expect(stage.locator("output")).toContainText("GPU");
    const sample = {
      statistics: await stage.locator("output").textContent(),
      renderer: await stage.locator("output").getAttribute("title"),
      frames: await stage.getAttribute("data-render-frames"),
    };
    await writeFile(
      "local/review/avatar-metrics.json",
      JSON.stringify(sample, null, 2),
    );
    await expect(stage.locator(".avatar-error")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
