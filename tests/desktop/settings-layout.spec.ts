import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("settings: focused categories, preserved drafts, keyboard navigation and compact layout", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-settings-layout-"));
  const app = await electron.launch({
    args: [
      "--mute-audio",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      ".",
    ],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    const navigation = page.getByRole("tablist", {
      name: "Разделы настроек",
      exact: true,
    });
    const choose = (name: string) =>
      navigation.getByRole("tab", { name, exact: true }).click();
    const visible = page.getByRole("tabpanel");
    await expect(visible).toHaveCount(1);
    await expect(visible).toHaveAttribute("id", "settings-panel-personality");
    await page.getByLabel("Имя", { exact: true }).fill("Уайли Черновик");
    await choose("Мозг");
    await page
      .getByLabel("Идентификатор модели", { exact: true })
      .fill("draft-model");
    await choose("Озвучка");
    await page
      .getByLabel("Движок озвучки", { exact: true })
      .selectOption("cloud");
    await expect(
      page.getByLabel("Облачный голос", { exact: true }),
    ).toBeVisible();
    await page.setViewportSize({ width: 1800, height: 1050 });
    await page.screenshot({
      path: "local/screenshots/settings-speech-wide.png",
      animations: "disabled",
    });
    await choose("Личность");
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue(
      "Уайли Черновик",
    );
    await choose("Мозг");
    await expect(
      page.getByLabel("Идентификатор модели", { exact: true }),
    ).toHaveValue("draft-model");
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Настройки сохранены");
    await choose("Микрофон и разговор");
    await page
      .getByRole("button", { name: "Освободить память речи", exact: true })
      .click();
    await expect(page.getByRole("status")).toHaveText(
      "Модели речи уже выгружены",
    );
    const idlePolicy = page.getByLabel("Автовыгрузка Whisper, Silero и Piper", {
      exact: true,
    });
    await expect(idlePolicy).toHaveValue("profile");
    await expect(page.locator(".voice-resources")).toContainText(
      "5 минут простоя",
    );
    await idlePolicy.selectOption("never");
    await expect(page.locator(".voice-resources")).toContainText(
      "остаются загруженными в простое",
    );
    await choose("Мозг");
    await choose("Микрофон и разговор");
    await expect(idlePolicy).toHaveValue("never");
    const recognitionQuality = page.getByRole("combobox", {
      name: "Точность распознавания",
      exact: true,
    });
    await expect(recognitionQuality).toHaveValue("accurate");
    await recognitionQuality.selectOption("balanced");
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Настройки сохранены");
    // A hidden category must not keep a microphone test recording in the background.
    await page.evaluate(() => {
      const original = navigator.mediaDevices.getUserMedia.bind(
        navigator.mediaDevices,
      );
      navigator.mediaDevices.getUserMedia = async (constraints) => {
        const stream = await original(constraints);
        Object.assign(window, { settingsTestTracks: stream.getTracks() });
        return stream;
      };
    });
    await page
      .getByRole("button", { name: "Проверить микрофон", exact: true })
      .click();
    await expect(
      page.getByRole("meter", { name: "Уровень микрофона", exact: true }),
    ).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() =>
          Array.isArray(
            (window as unknown as { settingsTestTracks?: MediaStreamTrack[] })
              .settingsTestTracks,
          ),
        ),
      )
      .toBe(true);
    await choose("Личность");
    await expect
      .poll(() =>
        page.evaluate(() =>
          (
            window as unknown as { settingsTestTracks: MediaStreamTrack[] }
          ).settingsTestTracks.map((track) => track.readyState),
        ),
      )
      .toEqual(["ended"]);
    await choose("Микрофон и разговор");
    // Card spacing follows document order, regardless of the previous category's height.
    const cards = await visible.locator(":scope > .card").all();
    const boxes = await Promise.all(cards.map((card) => card.boundingBox()));
    for (let i = 1; i < boxes.length; i++) {
      const gap = boxes[i]!.y - (boxes[i - 1]!.y + boxes[i - 1]!.height);
      expect(gap).toBeGreaterThanOrEqual(12);
      expect(gap).toBeLessThanOrEqual(16);
    }
    await navigation
      .getByRole("tab", { name: "Микрофон и разговор", exact: true })
      .focus();
    await page.keyboard.press("ArrowDown");
    await expect(
      navigation.getByRole("tab", { name: "Поиск", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("End");
    await expect(
      page.getByRole("heading", {
        name: "Резервные копии и перенос",
        exact: true,
      }),
    ).toBeVisible();
    await page.keyboard.press("Home");
    await expect(page.getByLabel("Имя", { exact: true })).toBeVisible();
    await page.screenshot({
      path: "local/screenshots/settings-personality-wide.png",
      animations: "disabled",
    });
    for (const width of [1000, 760]) {
      await page.setViewportSize({ width, height: 760 });
      for (const name of [
        "Личность",
        "Мозг",
        "Озвучка",
        "Микрофон и разговор",
        "Поиск",
        "Аватар",
        "Данные и копии",
      ]) {
        await choose(name);
        await expect(visible).toHaveCount(1);
        expect(
          await page
            .locator(".settings-page")
            .evaluate((element) => element.scrollWidth <= element.clientWidth),
        ).toBe(true);
      }
      await choose("Микрофон и разговор");
      await page.locator(".voice-resources").scrollIntoViewIfNeeded();
      await page.screenshot({
        path: `local/screenshots/settings-voice-idle-${width}.png`,
        animations: "disabled",
      });
      await choose("Озвучка");
      await page.locator(".settings-page").evaluate((element) => {
        element.scrollTop = element.scrollHeight;
      });
      const saveBox = await page
        .getByRole("button", { name: "Сохранить", exact: true })
        .boundingBox();
      const pageBox = await page.locator(".settings-page").boundingBox();
      expect(saveBox!.y).toBeGreaterThanOrEqual(pageBox!.y);
      expect(saveBox!.y + saveBox!.height).toBeLessThanOrEqual(
        pageBox!.y + pageBox!.height,
      );
      await page.locator(".settings-page").evaluate((element) => {
        element.scrollTop = 0;
      });
      await page.screenshot({
        path: `local/screenshots/settings-speech-${width}.png`,
        animations: "disabled",
      });
    }
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue(
      "Уайли Черновик",
    );
    await choose("Мозг");
    await expect(
      page.getByLabel("Идентификатор модели", { exact: true }),
    ).toHaveValue("draft-model");
    await choose("Микрофон и разговор");
    await expect(idlePolicy).toHaveValue("never");
    await expect(recognitionQuality).toHaveValue("balanced");
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
