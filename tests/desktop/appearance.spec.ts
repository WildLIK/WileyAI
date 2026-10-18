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
      ["ice", "Ледяной свет"],
      ["ember", "Красный контур"],
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
    await expect(page.locator("html")).toHaveAttribute("data-theme", "ember");
    await expect(page.locator("html")).toHaveAttribute(
      "data-motion",
      "reduced",
    );
    await expect(page.locator("html")).toHaveAttribute("data-glass", "off");
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
    await page.screenshot({ path: "local/screenshots/process-voice.png" });
    await expect(page.locator(".process-status")).toHaveCount(0, {
      timeout: 10000,
    });
  } finally {
    release();
    await app.close();
  }
});
