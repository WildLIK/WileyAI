import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { wav } from "../../src/voice/speech";

test("cloud speech: independent keys, all three previews, selected voice persistence and reference", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-cloud-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const keys = new Map<string, boolean>();
    const samples: {
      engine: string;
      cloud: {
        tts_model: string;
        tts_cloud_voice: string;
        tts_base_url: string;
        tts_use_reference: boolean;
      };
    }[] = [];
    // Intercept credential writes: never touch the user's real Windows keys.
    await page.route("**/voice/cloud/key", async (route) => {
      const body = route.request().postDataJSON();
      keys.set(body.base_url, !!body.api_key);
      await route.fulfill({ json: { has_key: !!body.api_key } });
    });
    await page.route("**/voice/cloud/connections", async (route) => {
      const response = await route.fetch();
      const info = await response.json();
      info.connections = info.connections.map((item: { base_url: string }) => ({
        ...item,
        has_key: keys.get(item.base_url) || false,
      }));
      await route.fulfill({ json: info });
    });
    await page.route("**/voice/synthesize", async (route) => {
      samples.push(route.request().postDataJSON());
      await route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(800), 16000)),
      });
    });
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByLabel("Движок озвучки", { exact: true })
      .selectOption("cloud");
    for (const name of ["OpenRouter", "RouterAI"]) {
      await page
        .getByLabel("Ключ озвучки " + name, { exact: true })
        .fill("synthetic-ui-test-key");
      await page
        .getByRole("button", { name: "Сохранить ключ " + name, exact: true })
        .click();
      await expect(
        page.getByLabel("Ключ озвучки " + name, { exact: true }),
      ).toHaveValue("");
    }
    for (const name of ["Fish Audio Free", "Gemini TTS", "Grok Voice"]) {
      await page
        .getByRole("button", { name: "Прослушать " + name, exact: true })
        .click();
      await expect(
        page.getByRole("button", { name: "Прослушать " + name, exact: true }),
      ).toBeEnabled();
    }
    expect(samples.map((item) => item.cloud.tts_model)).toEqual([
      "fish-audio/s2.1-pro-free:free",
      "google/gemini-3.8-flash-tts",
      "x-ai/grok-voice-tts-1.0",
    ]);
    expect(samples.map((item) => item.cloud.tts_cloud_voice)).toEqual([
      "",
      "Sulafat",
      "ara",
    ]);
    expect(samples.every((item) => item.engine === "cloud")).toBe(true);
    await expect(
      page.getByLabel("Облачная модель озвучки", { exact: true }),
    ).toHaveValue("fish-audio/s2.1-pro-free:free");
    await page.getByText("WAV-образец для Fish Audio", { exact: true }).click();
    await page
      .getByLabel("Загрузить WAV-образец", { exact: true })
      .setInputFiles({
        name: "sample.wav",
        mimeType: "audio/wav",
        buffer: Buffer.from(wav(new Float32Array(32000), 16000)),
      });
    await expect(
      page.getByLabel("Использовать WAV-образец для Fish", { exact: true }),
    ).toBeChecked();
    await expect(
      page.getByText("sample.wav · 2 с", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Прослушать Fish Audio Free", exact: true })
      .click();
    await expect.poll(() => samples.length).toBe(4);
    expect(samples[3].cloud.tts_use_reference).toBe(true);
    await expect(
      page.getByRole("button", { name: "Выбрать Grok Voice", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Выбрать Grok Voice", exact: true })
      .click();
    await expect(
      page.getByLabel("Облачная модель озвучки", { exact: true }),
    ).toHaveValue("x-ai/grok-voice-tts-1.0");
    await expect
      .poll(async () =>
        page.evaluate(async () => {
          const { url, token } = await window.wiley.connection();
          return (
            await (
              await fetch(url + "/settings", {
                headers: { Authorization: "Bearer " + token },
              })
            ).json()
          ).tts_model;
        }),
      )
      .toBe("x-ai/grok-voice-tts-1.0");
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await expect(
      page.getByLabel("Движок озвучки", { exact: true }),
    ).toHaveValue("cloud");
    await expect(
      page.getByLabel("Облачный голос или ID голоса", { exact: true }),
    ).toHaveValue("ara");
    await page
      .getByRole("heading", { name: "Облачная озвучка", exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: "local/screenshots/cloud-speech.png",
      fullPage: true,
    });
    expect(keys.size).toBe(2);
  } finally {
    await app.close();
  }
});
