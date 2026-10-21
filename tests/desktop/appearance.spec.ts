import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { wav } from "../../src/voice/speech";

async function config(page: Page) {
  return page.evaluate(async () => {
    const { url, token } = await window.wiley.connection();
    return (
      await fetch(url + "/settings", {
        headers: { Authorization: "Bearer " + token },
      })
    ).json();
  });
}

test("themes: live previews, preserved drafts, multiple windows, restart, light contrast and reduced motion", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-appearance-"));
  const launch = () =>
    electron.launch({
      args: ["--mute-audio", "."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await expect(page.locator(".process-status")).toHaveCount(0);
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByLabel("Имя", { exact: true })
      .fill("Не сохранять этот черновик");
    await page.getByRole("tab", { name: "Оформление", exact: true }).click();
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await expect(
      second.getByRole("heading", { name: "Настройки ассистента" }),
    ).toBeVisible();
    for (const [theme, name] of [
      ["ice", "Ледяной свет"],
      ["ember", "Красный контур"],
      ["aurora", "Аврора"],
      ["nebula", "Туманность"],
    ]) {
      await page.getByRole("button", { name: new RegExp("^" + name) }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(second.locator("html")).toHaveAttribute("data-theme", theme);
      await expect.poll(async () => (await config(page)).ui_theme).toBe(theme);
      await page.screenshot({
        path: `local/screenshots/theme-${theme}-settings.png`,
        animations: "disabled",
      });
    }
    await page.getByRole("button", { name: /^Ледяной свет/ }).click();
    const contrast = await page.evaluate(() => {
      const rgb = (value: string) =>
        value
          .match(/\d+/g)!
          .slice(0, 3)
          .map(Number)
          .map((x) => x / 255)
          .map((x) =>
            x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4,
          );
      const lum = (value: string) =>
        rgb(value).reduce(
          (sum, x, i) => sum + x * [0.2126, 0.7152, 0.0722][i],
          0,
        );
      const root = getComputedStyle(document.documentElement);
      const ink = lum(root.color),
        paper = lum(root.backgroundColor);
      return (Math.max(ink, paper) + 0.05) / (Math.min(ink, paper) + 0.05);
    });
    expect(contrast).toBeGreaterThan(7);
    await page.getByLabel("Полупрозрачные панели", { exact: false }).uncheck();
    await page.getByLabel("Уменьшить движение", { exact: false }).check();
    await expect(second.locator("html")).toHaveAttribute("data-glass", "off");
    await expect(second.locator("html")).toHaveAttribute(
      "data-motion",
      "reduced",
    );
    expect(
      await page
        .locator(".topbar")
        .evaluate((node) => getComputedStyle(node).backdropFilter),
    ).toBe("none");
    await page.getByRole("tab", { name: "Личность", exact: true }).click();
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue(
      "Не сохранять этот черновик",
    );
    expect((await config(page)).name).toBe("Уайли");
    await page.getByLabel("Имя", { exact: true }).fill("Уайли");
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    for (const [theme, name] of [
      ["aurora", "Аврора"],
      ["ice", "Ледяной свет"],
      ["ember", "Красный контур"],
      ["nebula", "Туманность"],
    ]) {
      await page.getByLabel("Выбрать тему оформления", { exact: true }).click();
      await page
        .getByRole("group", { name: "Быстрый выбор темы" })
        .getByRole("button", { name: new RegExp("^" + name) })
        .click();
      await expect(second.locator("html")).toHaveAttribute("data-theme", theme);
      await page.screenshot({
        path: `local/screenshots/theme-${theme}-chat.png`,
        animations: "disabled",
      });
    }
    await page.setViewportSize({ width: 900, height: 700 });
    const bounds = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      width: innerWidth,
    }));
    expect(bounds.scroll).toBeLessThanOrEqual(bounds.width);
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "nebula");
    await expect(page.locator(".nebula-canvas")).toHaveAttribute(
      "data-state",
      /still|paused/,
    );
    await expect(page.locator("html")).toHaveAttribute(
      "data-motion",
      "reduced",
    );
    await expect(page.locator("html")).toHaveAttribute("data-glass", "off");
  } finally {
    await app.close();
  }
});

test("nebula: real animated shader, bounded resolution, pause, reduced motion, context recovery and theme cleanup", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-nebula-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(() => {
      const native = WebGLRenderingContext.prototype.drawArrays;
      Object.assign(window, { nebulaFrames: 0 });
      WebGLRenderingContext.prototype.drawArrays = function (...args) {
        const state = window as unknown as { nebulaFrames: number };
        state.nebulaFrames++;
        return native.apply(this, args);
      };
    });
    await page.getByLabel("Выбрать тему оформления", { exact: true }).click();
    await page
      .getByRole("group", { name: "Быстрый выбор темы" })
      .getByRole("button", { name: /^Туманность/ })
      .click();
    await page.bringToFront();
    const canvas = page.locator(".nebula-canvas");
    await expect(canvas).toHaveAttribute("data-state", "running");
    await expect
      .poll(() =>
        page.evaluate(
          () => (window as unknown as { nebulaFrames: number }).nebulaFrames,
        ),
      )
      .toBeGreaterThan(4);
    const first = await canvas.screenshot();
    const measurement = await page.evaluate(async () => {
      const node = document.querySelector<HTMLCanvasElement>(".nebula-canvas")!;
      const state = window as unknown as { nebulaFrames: number };
      const start = state.nebulaFrames;
      await new Promise((resolve) => setTimeout(resolve, 600));
      return {
        frames: state.nebulaFrames - start,
        width: node.width,
        height: node.height,
      };
    });
    expect(measurement.frames).toBeGreaterThan(2);
    expect(measurement.frames).toBeLessThanOrEqual(16);
    expect(measurement.width).toBeLessThanOrEqual(960);
    expect(measurement.height).toBeLessThanOrEqual(540);
    expect((await canvas.screenshot()).equals(first)).toBe(false);
    await page.screenshot({
      path: "local/screenshots/theme-nebula-animated.png",
    });
    const assertStopped = async () =>
      expect(
        await page.evaluate(async () => {
          const state = window as unknown as { nebulaFrames: number };
          const start = state.nebulaFrames;
          await new Promise((resolve) => setTimeout(resolve, 200));
          return state.nebulaFrames - start;
        }),
      ).toBe(0);
    const nativeWindow = await app.browserWindow(page);
    await nativeWindow.evaluate((window) => window.blur());
    await expect(canvas).toHaveAttribute("data-state", "running");
    await nativeWindow.evaluate((window) => window.hide());
    await expect(canvas).toHaveAttribute("data-state", "paused");
    await assertStopped();
    await nativeWindow.evaluate((window) => {
      window.show();
      window.focus();
    });
    await expect(canvas).toHaveAttribute("data-state", "running");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(canvas).toHaveAttribute("data-state", "still");
    await assertStopped();
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await expect(canvas).toHaveAttribute("data-state", "running");
    await canvas.evaluate((node) => {
      const ext = (node as HTMLCanvasElement)
        .getContext("webgl")!
        .getExtension("WEBGL_lose_context")!;
      Object.assign(window, { restoreNebula: () => ext.restoreContext() });
      ext.loseContext();
    });
    await expect(canvas).toHaveAttribute("data-state", "fallback");
    await assertStopped();
    await page.evaluate(() =>
      (window as unknown as { restoreNebula(): void }).restoreNebula(),
    );
    await expect(canvas).toHaveAttribute("data-state", "running");
    await page.getByLabel("Выбрать тему оформления", { exact: true }).click();
    await page
      .getByRole("group", { name: "Быстрый выбор темы" })
      .getByRole("button", { name: /^Аврора/ })
      .click();
    await expect(canvas).toHaveCount(0);
    await assertStopped();
    // A driver without WebGL keeps the palette and a static gradient, with no loop.
    await page.evaluate(() => {
      const native = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (...args) {
        if (String(args[0]) === "webgl") return null;
        return Reflect.apply(native, this, args);
      } as typeof native;
    });
    await page.getByLabel("Выбрать тему оформления", { exact: true }).click();
    await page
      .getByRole("group", { name: "Быстрый выбор темы" })
      .getByRole("button", { name: /^Туманность/ })
      .click();
    await expect(canvas).toHaveAttribute("data-state", "fallback");
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Фон не мешает вводу");
    await assertStopped();
  } finally {
    await app.close();
  }
});

test("process animations follow real pending reply and speech states, and disappear on completion", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-processes-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  let release: () => void = () => {};
  const ready = new Promise<void>((resolve) => {
    release = resolve;
  });
  try {
    const page = await app.firstWindow();
    // The compact layout intentionally hides the header's speech status.
    await page.setViewportSize({ width: 1920, height: 1000 });
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      await fetch(url + "/settings/speech", {
        method: "PUT",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tts_engine: "sapi", speak_answers: true }),
      });
    });
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.route("**/voice/synthesize", async (route) => {
      await ready;
      await route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(32000), 16000)),
      });
    });
    await page.evaluate(() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        if (!String(args[0]).endsWith("/chat")) return original(...args);
        const encoder = new TextEncoder();
        return new Response(
          new ReadableStream({
            start(controller) {
              const emit = (value: unknown) =>
                controller.enqueue(
                  encoder.encode("data: " + JSON.stringify(value) + "\n\n"),
                );
              emit({ type: "stage", text: "Ищу в интернете…" });
              Object.assign(window, {
                processStage: (text: string) => emit({ type: "stage", text }),
                processText: () =>
                  emit({ type: "delta", text: "Готовая фраза для озвучки." }),
                processFinish: () => {
                  emit({
                    type: "done",
                    message: {
                      id: "process-answer",
                      role: "assistant",
                      content: "Готовая фраза для озвучки.",
                      created: new Date().toISOString(),
                    },
                  });
                  controller.close();
                },
              });
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      };
    });
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Проверка процессов");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator('[data-process="search"]')).toBeVisible();
    await page.evaluate(() =>
      (window as unknown as { processStage(text: string): void }).processStage(
        "Формирую ответ…",
      ),
    );
    await expect(
      page.locator('.message[aria-busy] [data-process="brain"]'),
    ).toBeVisible();
    const orbit = page.locator(".message[aria-busy] .process-orbit");
    const offset = () =>
      orbit.evaluate((node) => getComputedStyle(node).strokeDashoffset);
    const before = await offset();
    await expect.poll(offset).not.toBe(before);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect
      .poll(() =>
        orbit.evaluate((node) => getComputedStyle(node).animationName),
      )
      .toBe("none");
    const still = await offset();
    await page.waitForTimeout(150);
    expect(await offset()).toBe(still);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await expect
      .poll(() =>
        orbit.evaluate((node) => getComputedStyle(node).animationName),
      )
      .toBe("process-orbit-travel");
    await page.evaluate(() =>
      (window as unknown as { processText(): void }).processText(),
    );
    await expect(
      page.getByText("Готовлю озвучку…", { exact: true }),
    ).toBeVisible();
    await page.evaluate(() =>
      (window as unknown as { processFinish(): void }).processFinish(),
    );
    await expect(page.locator(".message[aria-busy]")).toHaveCount(0);
    await expect(
      page.getByText("Готовлю озвучку…", { exact: true }),
    ).toBeVisible();
    release();
    await expect(
      page.getByText("Озвучиваю ответ", { exact: true }),
    ).toBeVisible();
    await expect(
      page.locator('[data-process="voice"] .process-orbit'),
    ).toBeVisible();
    await page.screenshot({ path: "local/screenshots/process-voice.png" });
    await expect(page.locator(".process-status")).toHaveCount(0, {
      timeout: 10000,
    });
  } finally {
    release();
    await app.close();
  }
});

test("avatar: transparent drag area and settings beside click-through fit the smallest window", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-avatar-controls-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    const settings = avatar.getByRole("button", {
      name: "Открыть настройки",
      exact: true,
    });
    await expect(settings).toBeVisible();
    await expect(
      avatar.getByRole("button", { name: "Закрыть окно аватара", exact: true }),
    ).toBeVisible();
    expect(
      await avatar
        .locator(".pet-drag")
        .evaluate((node) =>
          getComputedStyle(node).getPropertyValue("-webkit-app-region"),
        ),
    ).toBe("drag");
    const controls = await avatar
      .locator(".pet-close, .pet-monitor, .pet-size-controls, .pet-resize")
      .evaluateAll((nodes) =>
        nodes.map((node) =>
          getComputedStyle(node).getPropertyValue("-webkit-app-region"),
        ),
      );
    expect(controls).toEqual(["no-drag", "no-drag", "no-drag", "no-drag"]);
    expect(
      await avatar
        .locator(".pet-drag")
        .evaluate((node) => getComputedStyle(node).backgroundColor),
    ).toBe("rgba(0, 0, 0, 0)");
    expect(
      await settings.evaluate((node) =>
        node.previousElementSibling?.textContent?.trim(),
      ),
    ).toBe("Пропуск кликов");
    for (const width of [360, 300]) {
      await avatar.setViewportSize({ width, height: 570 });
      const layout = await avatar.locator(".pet-actions").evaluate((node) => {
        const box = node.getBoundingClientRect();
        return {
          fits: node.scrollWidth <= node.clientWidth,
          buttons: [...node.querySelectorAll("button")].map((button) => {
            const child = button.getBoundingClientRect();
            return (
              child.left >= box.left &&
              child.right <= box.right &&
              child.top >= box.top &&
              child.bottom <= box.bottom
            );
          }),
        };
      });
      expect(layout.fits).toBe(true);
      expect(layout.buttons).toEqual([true, true, true, true]);
    }
    await avatar.screenshot({
      path: "local/screenshots/avatar-transparent-toolbar.png",
      omitBackground: true,
    });
    const settingsWindow = app.waitForEvent("window");
    await settings.click();
    const preferences = await settingsWindow;
    await expect(
      preferences.getByRole("heading", { name: "Настройки ассистента" }),
    ).toBeVisible();
  } finally {
    await app.close();
  }
});
