import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { wav } from "../../src/voice/speech";

test("voice choice saves immediately, streams before done, and stop discards the rest", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-streaming-"));
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
    await page.route("**/voice", (route) =>
      route.fulfill({
        json: {
          available: true,
          installed_stt: ["small"],
          voices: [],
          qwen3_voices: [{ name: "serena", language: "Serena" }],
        },
      }),
    );
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByLabel("Имя", { exact: true })
      .fill("Несохранённый характер");
    await page
      .getByLabel("Движок озвучки", { exact: true })
      .selectOption("qwen3");
    await page
      .getByLabel("Голос ассистента", { exact: true })
      .selectOption("serena");
    await page
      .getByLabel("Озвучивать ответы автоматически", { exact: true })
      .check();
    const savedVoice = () =>
      page.evaluate(async () => {
        const { url, token } = await window.wiley.connection();
        return (
          await fetch(url + "/settings", {
            headers: { Authorization: "Bearer " + token },
          })
        ).json();
      });
    await expect
      .poll(async () => (await savedVoice()).tts_voice)
      .toBe("serena");
    expect((await savedVoice()).name).toBe("Уайли");
    await page
      .getByRole("button", { name: "＋ Новый чат", exact: true })
      .click();
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeEnabled();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue(
      "Несохранённый характер",
    );
    await expect(
      page.getByLabel("Движок озвучки", { exact: true }),
    ).toHaveValue("qwen3");
    await expect(
      page.getByLabel("Голос ассистента", { exact: true }),
    ).toHaveValue("serena");
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await expect(
      second.getByLabel("Движок озвучки", { exact: true }),
    ).toHaveValue("qwen3");
    await expect(
      second.getByLabel("Голос ассистента", { exact: true }),
    ).toHaveValue("serena");
    await second
      .getByLabel("Устройство Qwen3-TTS", { exact: true })
      .selectOption("cpu");
    await expect(
      page.getByLabel("Устройство Qwen3-TTS", { exact: true }),
    ).toHaveValue("cpu");
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue(
      "Несохранённый характер",
    );
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    const synthesis: {
      text: string;
      voice: string;
      engine: string;
      session_id: string;
    }[] = [];
    await page.route("**/voice/synthesize", (route) => {
      synthesis.push(route.request().postDataJSON());
      return route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(16000), 16000)),
      });
    });
    await page.evaluate(() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        if (!String(args[0]).endsWith("/chat")) return original(...args);
        const encoder = new TextEncoder();
        const user = {
          id: "stream-user",
          role: "user",
          content: "Привет",
          created: new Date().toISOString(),
        };
        const body = new ReadableStream({
          start(controller) {
            const emit = (event: unknown) =>
              controller.enqueue(
                encoder.encode("data: " + JSON.stringify(event) + "\n\n"),
              );
            emit({ type: "user", message: user });
            emit({ type: "delta", text: "Первая готовая фраза. " });
            Object.assign(window, {
              finishReply: () => {
                emit({ type: "delta", text: "Вторая фраза после остановки." });
                emit({
                  type: "done",
                  message: {
                    ...user,
                    id: "stream-answer",
                    role: "assistant",
                    content:
                      "Первая готовая фраза. Вторая фраза после остановки.",
                  },
                });
                controller.close();
              },
            });
          },
        });
        return new Response(body, {
          headers: { "Content-Type": "text/event-stream" },
        });
      };
    });
    await page.getByLabel("Сообщение", { exact: true }).fill("Проверим голос");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect.poll(() => synthesis.length).toBe(1);
    expect(synthesis[0]).toMatchObject({
      engine: "qwen3",
      voice: "serena",
      text: "Первая готовая фраза.",
    });
    expect(synthesis[0].session_id).toBeTruthy();
    await expect(
      page.locator('.message.assistant[aria-busy="true"]'),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "■ Остановить озвучку", exact: true })
      .click();
    await page.evaluate(() =>
      (window as unknown as { finishReply(): void }).finishReply(),
    );
    await expect(
      page.getByRole("button", { name: "Отправить", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "■ Остановить озвучку", exact: true }),
    ).toBeHidden();
    expect(synthesis).toHaveLength(1);
    await expect(page.getByRole("alert")).toBeHidden();
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("button", { name: "Начать разговор", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await expect(
      page.getByLabel("Движок озвучки", { exact: true }),
    ).toHaveValue("qwen3");
    // The real voice catalogue includes Serena after restart, even without model weights.
    await expect(
      page.getByLabel("Голос ассистента", { exact: true }),
    ).toHaveValue("serena");
    await expect(
      page.getByLabel("Озвучивать ответы автоматически", { exact: true }),
    ).toBeChecked();
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue("Уайли");
  } finally {
    await app.close();
  }
});
