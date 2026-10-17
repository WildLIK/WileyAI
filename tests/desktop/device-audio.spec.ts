import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("Windows audio: controls, permission changes, stale slider and narrow layout without changing real audio", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-device-audio-"));
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
    let volume = 37;
    let muted = false;
    let enabled = true;
    const calls: { action: string; value?: number }[] = [];
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/tools\/access$/,
      async (route) => {
        enabled = route.request().postDataJSON().allow_audio_control;
        await route.continue();
      },
    );
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/device\/audio$/,
      async (route) => {
        if (route.request().method() === "GET") {
          await route.fulfill({
            json: { available: true, enabled, volume, muted },
          });
          return;
        }
        const body = route.request().postDataJSON();
        calls.push(body);
        if (body.action === "set_volume") volume = body.value;
        if (body.action === "change_volume")
          volume = Math.max(0, Math.min(100, volume + body.value));
        if (body.action === "mute") muted = true;
        if (body.action === "unmute") muted = false;
        await route.fulfill({
          json: {
            volume,
            muted,
            text:
              body.action === "next"
                ? "Windows получила медиаклавишу «Следующий трек»."
                : `Громкость Windows: ${volume}%. ${muted ? "Звук выключен." : "Звук включён."}`,
          },
        });
      },
    );
    await page.getByRole("button", { name: "⌘ Команды", exact: true }).click();
    const panel = page.getByLabel("Звук Windows", { exact: true });
    const slider = panel.getByRole("slider", {
      name: "Громкость Windows",
      exact: true,
    });
    await expect(slider).toHaveValue("37");
    await slider.press("ArrowRight");
    await expect(slider).toHaveValue("38");
    await panel.getByRole("button", { name: "Обновить громкость" }).click();
    await expect(slider).toHaveValue("38");
    expect(calls).toEqual([]);
    await panel.getByRole("button", { name: "Применить громкость" }).click();
    await expect(panel.getByRole("status")).toContainText("38%");
    await panel.getByRole("button", { name: "Тише на 10%" }).click();
    await expect(slider).toHaveValue("28");
    await panel
      .getByRole("button", { name: "Выключить звук", exact: true })
      .click();
    await expect(
      panel.getByRole("button", { name: "Включить звук", exact: true }),
    ).toBeVisible();
    await panel
      .getByRole("button", { name: "Включить звук", exact: true })
      .click();
    await expect(
      panel.getByRole("button", { name: "Выключить звук", exact: true }),
    ).toBeVisible();
    await panel
      .getByRole("button", { name: "Следующий трек", exact: true })
      .click();
    await expect(panel.getByRole("status")).toContainText("медиаклавишу");
    expect(calls.map((item) => item.action)).toEqual([
      "set_volume",
      "change_volume",
      "mute",
      "unmute",
      "next",
    ]);
    const access = page.getByLabel("Доступ к инструментам", { exact: true });
    await access
      .getByLabel("Управлять звуком и медиаклавишами Windows")
      .uncheck();
    await access.getByRole("button", { name: "Сохранить доступ" }).click();
    await expect(access.getByRole("status")).toContainText("Доступ сохранён");
    await expect(slider).toBeDisabled();
    await expect(
      panel.getByRole("button", { name: "Следующий трек", exact: true }),
    ).toBeDisabled();
    await page.setViewportSize({ width: 820, height: 900 });
    await panel.scrollIntoViewIfNeeded();
    const box = await panel.boundingBox();
    expect(box!.width).toBeLessThan(820);
    expect(box!.x).toBeGreaterThanOrEqual(0);
    await page.screenshot({
      path: "local/screenshots/device-audio.png",
      animations: "disabled",
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
