import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { wav } from "../../src/voice/speech";

test("cloud speech: compact service settings, female reference and persisted independent choices", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-cloud-"));
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
    let femaleReference = false;
    // All credential writes and cloud synthesis are mocked; user keys are never changed.
    await page.route("**/voice/cloud/key", async (route) => {
      const body = route.request().postDataJSON();
      keys.set(body.base_url, !!body.api_key);
      await route.fulfill({ json: { has_key: !!body.api_key } });
    });
    await page.route("**/voice/cloud/connections", async (route) => {
      const info = await (await route.fetch()).json();
      info.connections = info.connections.map((item: { base_url: string }) => ({
        ...item,
        has_key: keys.get(item.base_url) || false,
      }));
      info.serena_available = true;
      if (femaleReference)
        info.reference = { name: "Serena · локальный пример.wav", seconds: 3 };
      await route.fulfill({ json: info });
    });
    await page.route("**/voice/cloud/reference/serena", async (route) => {
      femaleReference = true;
      await route.fulfill({
        json: {
          reference: { name: "Serena · локальный пример.wav", seconds: 3 },
          serena_available: true,
        },
      });
    });
    await page.route("**/voice/synthesize", async (route) => {
      samples.push(route.request().postDataJSON());
      await route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(800), 16000)),
      });
    });
    const group = page.getByRole("group", {
      name: "Облачная озвучка",
      exact: true,
    });
    const service = page.getByLabel("Сервис озвучки", { exact: true });
    const model = page.getByLabel("Облачная модель озвучки", { exact: true });
    const preview = page.getByRole("button", {
      name: "♪ Прослушать голос",
      exact: true,
    });
    const settings = () =>
      page.evaluate(async () => {
        const { url, token } = await window.wiley.connection();
        return (
          await fetch(url + "/settings", {
            headers: { Authorization: "Bearer " + token },
          })
        ).json();
      });
    const saveKey = async (name: string) => {
      await page
        .getByLabel("Ключ озвучки " + name, { exact: true })
        .fill("synthetic-ui-test-key");
      await page
        .getByRole("button", { name: "Сохранить ключ " + name, exact: true })
        .click();
      await expect(
        page.getByText("Ключ " + name + " · сохранён", { exact: true }),
      ).toBeVisible();
      await expect(
        page.getByLabel("Ключ озвучки " + name, { exact: true }),
      ).not.toBeVisible();
    };
    const listen = async () => {
      const count = samples.length;
      await preview.click();
      await expect.poll(() => samples.length).toBe(count + 1);
      await expect(preview).toBeEnabled();
    };
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    await page
      .getByLabel("Движок озвучки", { exact: true })
      .selectOption("cloud");
    await expect(
      page.getByLabel("Ключ озвучки RouterAI", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByLabel("Адрес API озвучки", { exact: true }),
    ).not.toBeVisible();
    await saveKey("OpenRouter");
    await listen();
    await group.getByText("WAV-образец голоса", { exact: true }).click();
    // Uploading a real file exercises the temporary local core, without any cloud request.
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
      page.getByText("Голос из образца: sample.wav · 2 с", { exact: true }),
    ).toBeVisible();
    await listen();
    await page
      .getByRole("button", {
        name: "Женский голос · образец Serena",
        exact: true,
      })
      .click();
    await expect(
      page.getByText("Голос из образца: Serena · локальный пример.wav · 3 с", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(service).toBeEnabled();
    await listen();
    expect(samples[2].cloud.tts_use_reference).toBe(true);
    expect(samples[2].cloud.tts_cloud_voice).toBe("");
    expect(samples[2].cloud.tts_model).toBe("fish-audio/s2.1-pro-free:free");
    const voiceSelect = page.getByLabel("Облачный голос", { exact: true });
    await voiceSelect.selectOption("ff1ae409865e4c7493db061913d77a79");
    await expect(
      page.getByLabel("Использовать WAV-образец для Fish", { exact: true }),
    ).not.toBeChecked();
    await group
      .getByText("Дополнительно: API, голос и формат", { exact: true })
      .click();
    const voiceLink = page.getByLabel("Ссылка или ID голоса Fish Audio", {
      exact: true,
    });
    await voiceLink.fill(
      "https://fish.audio/ru/m/ff1ae409865e4c7493db061913d77a79/?share=1",
    );
    await voiceLink.blur();
    await listen();
    expect(samples[3].cloud.tts_cloud_voice).toBe(
      "ff1ae409865e4c7493db061913d77a79",
    );
    expect(samples[3].cloud.tts_use_reference).toBe(false);
    await voiceSelect.selectOption("303b89e345f04bf4b3755e0ddf1b41c4");
    await expect(voiceSelect).toHaveValue("303b89e345f04bf4b3755e0ddf1b41c4");
    await listen();
    expect(samples[4].cloud.tts_cloud_voice).toBe(
      "303b89e345f04bf4b3755e0ddf1b41c4",
    );
    expect(samples[4].cloud.tts_use_reference).toBe(false);
    await group
      .getByText("Дополнительно: API, голос и формат", { exact: true })
      .click();
    await group.getByText("WAV-образец голоса", { exact: true }).click();
    await voiceSelect.selectOption("$add");
    await page
      .getByLabel("Название голоса", { exact: true })
      .fill("Мой персонаж");
    await page
      .getByLabel("Ссылка или ID голоса", { exact: true })
      .fill("https://fish.audio/ru/m/" + "a".repeat(32) + "/");
    await page
      .getByRole("button", { name: "Добавить голос", exact: true })
      .click();
    await expect(voiceSelect).toHaveValue("a".repeat(32));
    await expect(
      voiceSelect.locator("option", { hasText: "Мой персонаж" }),
    ).toHaveCount(1);
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    await expect(voiceSelect).toHaveValue("a".repeat(32));
    expect((await settings()).tts_saved_voices[0].name).toBe("Мой персонаж");
    await voiceSelect.selectOption("303b89e345f04bf4b3755e0ddf1b41c4");
    await group.screenshot({
      path: "local/screenshots/cloud-speech-fish-compact.png",
    });

    await service.selectOption("routerai");
    await expect(model).toHaveValue("google/gemini-3.8-flash-tts");
    await expect(
      page.getByLabel("Ключ озвучки OpenRouter", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", {
        name: "Женский голос · образец Serena",
        exact: true,
      }),
    ).toHaveCount(0);
    await expect(
      page.getByLabel("Облачный голос", { exact: true }),
    ).toHaveValue("Sulafat");
    await expect(
      voiceSelect.locator("option", { hasText: "Мой персонаж" }),
    ).toHaveCount(0);
    await saveKey("RouterAI");
    await listen();
    await model.selectOption("google/gemini-3.8-flash-lite-tts");
    await page
      .getByLabel("Облачный голос", { exact: true })
      .selectOption("Achernar");
    await listen();
    await model.selectOption("x-ai/grok-voice-tts-1.0");
    await expect(
      page.getByLabel("Облачный голос", { exact: true }),
    ).toHaveValue("ara");
    await page
      .getByLabel("Облачный голос", { exact: true })
      .selectOption("eve");
    await listen();
    expect(samples.map((item) => item.cloud.tts_model)).toEqual([
      "fish-audio/s2.1-pro-free:free",
      "fish-audio/s2.1-pro-free:free",
      "fish-audio/s2.1-pro-free:free",
      "fish-audio/s2.1-pro-free:free",
      "fish-audio/s2.1-pro-free:free",
      "google/gemini-3.8-flash-tts",
      "google/gemini-3.8-flash-lite-tts",
      "x-ai/grok-voice-tts-1.0",
    ]);
    expect(samples.map((item) => item.cloud.tts_cloud_voice)).toEqual([
      "",
      "",
      "",
      "ff1ae409865e4c7493db061913d77a79",
      "303b89e345f04bf4b3755e0ddf1b41c4",
      "Sulafat",
      "Achernar",
      "eve",
    ]);
    expect(samples.every((item) => item.engine === "cloud")).toBe(true);
    await service.selectOption("openrouter");
    await expect(model).toHaveValue("fish-audio/s2.1-pro-free:free");
    await expect(
      page.getByLabel("Использовать WAV-образец для Fish", { exact: true }),
    ).not.toBeChecked();
    expect((await settings()).tts_cloud_voice).toBe(
      "303b89e345f04bf4b3755e0ddf1b41c4",
    );
    await service.selectOption("routerai");
    await expect(model).toHaveValue("x-ai/grok-voice-tts-1.0");
    await expect(
      page.getByLabel("Облачный голос", { exact: true }),
    ).toHaveValue("eve");
    await expect(service).toBeEnabled();
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    await expect(model).toHaveValue("x-ai/grok-voice-tts-1.0");
    await expect(
      page.getByLabel("Облачный голос", { exact: true }),
    ).toHaveValue("eve");
    await group.screenshot({
      path: "local/screenshots/cloud-speech-routerai-compact.png",
    });

    // While a profile is loading, do not expose a new service with old fields.
    let resumeSwitch!: () => void;
    const pausedSwitch = new Promise<void>((resolve) => {
      resumeSwitch = resolve;
    });
    let switching = false;
    await page.route(
      "**/settings/speech",
      async (route) => {
        switching = true;
        await pausedSwitch;
        await route.continue();
      },
      { times: 1 },
    );
    await service.selectOption("compatible");
    try {
      await expect.poll(() => switching).toBe(true);
      await expect(service).toBeDisabled();
      await expect(service).toHaveValue("routerai");
      await expect(
        page.getByLabel("Адрес API озвучки", { exact: true }),
      ).not.toBeVisible();
    } finally {
      resumeSwitch();
    }
    const address = page.getByLabel("Адрес API озвучки", { exact: true });
    await expect(address).toHaveValue("https://api.example.com/v1");
    await address.fill("https://speech.example.org/v1");
    await address.blur();
    await expect(service).toBeEnabled();
    const modelId = page.getByLabel("ID облачной модели озвучки", {
      exact: true,
    });
    await modelId.fill("custom-speech");
    await modelId.blur();
    await expect(service).toBeEnabled();
    await group
      .getByText("Дополнительно: API, голос и формат", { exact: true })
      .click();
    const customVoice = page.getByLabel("Облачный голос или ID голоса", {
      exact: true,
    });
    await customVoice.fill("my-voice");
    await customVoice.blur();
    await saveKey("Совместимый API");
    await service.selectOption("openrouter");
    await expect(model).toHaveValue("fish-audio/s2.1-pro-free:free");
    await service.selectOption("compatible");
    await expect(model).toHaveValue("custom-speech");
    await expect(address).toHaveValue("https://speech.example.org/v1");
    await expect(
      page.getByLabel("Облачный голос", { exact: true }),
    ).toHaveValue("my-voice");
    const saved = await settings();
    expect(saved.tts_connections.routerai.tts_cloud_voice).toBe("eve");
    expect(JSON.stringify(saved)).not.toContain("synthetic-ui-test-key");
    expect(keys.size).toBe(3);

    await service.selectOption("openrouter");
    await expect(
      voiceSelect.locator("option", { hasText: "Мой персонаж" }),
    ).toHaveCount(1);
    await voiceSelect.selectOption("a".repeat(32));
    await page
      .getByRole("button", {
        name: "Удалить голос «Мой персонаж» из списка",
        exact: true,
      })
      .click();
    await expect(
      voiceSelect.locator("option", { hasText: "Мой персонаж" }),
    ).toHaveCount(0);
    expect((await settings()).tts_saved_voices).toEqual([]);
    await voiceSelect.selectOption("303b89e345f04bf4b3755e0ddf1b41c4");
    await page.setViewportSize({ width: 950, height: 750 });
    await expect(service).toBeEnabled();
    await group.scrollIntoViewIfNeeded();
    expect(
      await group.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true);
    await group.screenshot({
      path: "local/screenshots/cloud-speech-narrow.png",
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
