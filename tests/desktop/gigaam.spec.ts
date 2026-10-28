import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { wav } from "../../src/voice/speech";

test("GigaAM selection persists, disables Whisper search controls and remains available in the catalog", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-gigaam-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  const page = await app.firstWindow();
  try {
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const before = await page.evaluate(async () => {
      const c = await window.wiley.connection();
      return (
        await fetch(c.url + "/settings", {
          headers: { Authorization: "Bearer " + c.token },
        })
      ).json();
    });
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Микрофон и разговор", exact: true })
      .click();
    const model = page.getByLabel("Модель распознавания", { exact: true });
    const quality = page.getByLabel("Точность распознавания", { exact: true });
    await model.selectOption("gigaam-v3");
    await expect(quality).toBeDisabled();
    await expect(
      page.getByText("GigaAM распознаёт русскую речь локально", {
        exact: false,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect
      .poll(() =>
        page.evaluate(async () => {
          const c = await window.wiley.connection();
          return (
            await fetch(c.url + "/settings", {
              headers: { Authorization: "Bearer " + c.token },
            })
          ).json();
        }),
      )
      .toMatchObject({
        stt_model: "gigaam-v3",
        tts_engine: before.tts_engine,
        tts_voice: before.tts_voice,
      });
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Микрофон и разговор", exact: true })
      .click();
    await expect(model).toHaveValue("gigaam-v3");
    await expect(quality).toBeDisabled();
    await model.selectOption("small");
    await expect(quality).toBeEnabled();
    await page.getByRole("button", { name: "⬡ Модели", exact: true }).click();
    await page
      .getByRole("tab", { name: "Распознавание голоса", exact: false })
      .click();
    const card = page.locator("article").filter({
      has: page.getByRole("heading", {
        name: "GigaAM v3 · E2E RNN-T",
        exact: true,
      }),
    });
    await expect(card).toContainText("854 МиБ");
    await expect(
      card.getByRole("button", { name: "↓ Скачать", exact: true }),
    ).toBeEnabled();
    await expect(
      page.getByRole("heading", { name: "Whisper · small", exact: true }),
    ).toBeVisible();
    await page.screenshot({ path: "local/review/gigaam-catalog.png" });
  } finally {
    await app.close();
  }
});

test("GigaAM manual recording works without the Whisper component", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-gigaam-mic-"));
  const input = join(data, "microphone.wav");
  await writeFile(input, Buffer.from(wav(new Float32Array(48000), 16000)));
  const app = await electron.launch({
    args: [
      "--mute-audio",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${input}`,
      ".",
    ],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  const page = await app.firstWindow();
  try {
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(async () => {
      const c = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + c.token,
        "Content-Type": "application/json",
      };
      const settings = await (
        await fetch(c.url + "/settings", { headers })
      ).json();
      const response = await fetch(c.url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({ ...settings, stt_model: "gigaam-v3" }),
      });
      if (!response.ok) throw new Error(await response.text());
    });
    await page.route("**/voice", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        json: {
          ...(await response.json()),
          available: false,
          gigaam_available: true,
          installed_stt: ["gigaam-v3"],
        },
      });
    });
    let recordings = 0;
    await page.route("**/voice/transcribe", async (route) => {
      recordings++;
      expect(route.request().postDataBuffer()?.length).toBeGreaterThan(100);
      await route.fulfill({ json: { text: "Проверка GigaAM без Whisper." } });
    });
    await page.reload();
    await page
      .getByRole("button", { name: "Записать голос", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Остановить запись", exact: true }),
    ).toBeVisible();
    await page.waitForTimeout(250);
    await page
      .getByRole("button", { name: "Остановить запись", exact: true })
      .click();
    await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue(
      "Проверка GigaAM без Whisper.",
    );
    expect(recordings).toBe(1);
  } finally {
    await app.close();
  }
});
