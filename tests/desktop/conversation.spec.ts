import {
  test,
  expect,
  _electron as electron,
  type Page,
  type Route,
} from "@playwright/test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { wav } from "../../src/voice/speech";

type AudioStats = { frames: number; peak: number; context: string };
const audioStats = (page: Page) =>
  page.evaluate(
    () => (window as unknown as { testAudioStats: AudioStats }).testAudioStats,
  );

async function launch(dataDir?: string) {
  const data =
    dataDir || (await mkdtemp(join(tmpdir(), "wileyai-conversation-")));
  const sampleRate = 48000;
  const samples = new Float32Array(sampleRate * 5);
  // The fake microphone repeats: a short tone, then enough silence to end a phrase.
  for (let n = sampleRate; n < sampleRate * 1.8; n++)
    samples[n] = 0.3 * Math.sin((2 * Math.PI * 220 * n) / sampleRate);
  const input = join(data, "microphone.wav");
  await writeFile(input, Buffer.from(wav(samples, sampleRate)));
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
  await expect(
    page.getByRole("heading", { name: "Привет, я Уайли." }),
  ).toBeVisible();
  const instrument = () => {
    const stats = { frames: 0, peak: 0, context: "" };
    Object.assign(window, { testAudioStats: stats });
    const Worklet = window.AudioWorkletNode;
    window.AudioWorkletNode = class extends Worklet {
      constructor(
        context: BaseAudioContext,
        name: string,
        options?: AudioWorkletNodeOptions,
      ) {
        super(context, name, options);
        context.addEventListener("statechange", () => {
          stats.context = context.state;
        });
        this.port.addEventListener("message", (event) => {
          stats.frames++;
          stats.context = context.state;
          for (const value of event.data as Float32Array)
            stats.peak = Math.max(stats.peak, Math.abs(value));
        });
        this.port.start();
      }
    };
    const original = navigator.mediaDevices.getUserMedia.bind(
      navigator.mediaDevices,
    );
    const tracks: MediaStreamTrack[] = [];
    Object.assign(window, { testMicTracks: tracks });
    navigator.mediaDevices.getUserMedia = async (options) => {
      const stream = await original(options);
      tracks.push(...stream.getTracks());
      return stream;
    };
  };
  await page.addInitScript(instrument);
  await page.evaluate(instrument);
  return { app, page, data };
}

async function micStopped(page: Page, count = 1) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as unknown as { testMicTracks: MediaStreamTrack[] }
        ).testMicTracks.map((t) => t.readyState),
      ),
    )
    .toEqual(Array(count).fill("ended"));
}

async function startLayoutProbe(page: Page) {
  await page.evaluate(async () => {
    await new Promise(requestAnimationFrame);
    const read = () =>
      [
        ".chat-toolbar",
        ".message-scroll-area",
        ".composer-area",
        ".companion-panel",
      ].map((selector) => {
        const box = document.querySelector(selector)!.getBoundingClientRect();
        return { selector, top: box.top, height: box.height };
      });
    const baseline = read();
    const samples: { phase: string; boxes: ReturnType<typeof read> }[] = [];
    const observer = new MutationObserver(() => {
      samples.push({
        phase:
          document.querySelector(".conversation-phase")?.textContent || "idle",
        boxes: read(),
      });
    });
    observer.observe(document.querySelector(".workspace")!, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    Object.assign(window, {
      layoutProbe: { baseline, samples, stop: () => observer.disconnect() },
    });
  });
}

async function expectStableLayout(page: Page) {
  const result = await page.evaluate(() => {
    const probe = (
      window as unknown as {
        layoutProbe: {
          baseline: { selector: string; top: number; height: number }[];
          samples: {
            phase: string;
            boxes: { selector: string; top: number; height: number }[];
          }[];
          stop(): void;
        };
      }
    ).layoutProbe;
    probe.stop();
    return { baseline: probe.baseline, samples: probe.samples };
  });
  expect(result.samples.length).toBeGreaterThan(0);
  for (const sample of result.samples)
    for (const [index, box] of sample.boxes.entries()) {
      const reference = result.baseline[index];
      expect(
        Math.abs(box.top - reference.top),
        `${sample.phase}: ${box.selector} moved`,
      ).toBeLessThanOrEqual(1);
      expect(
        Math.abs(box.height - reference.height),
        `${sample.phase}: ${box.selector} resized`,
      ).toBeLessThanOrEqual(1);
    }
}

test("conversation: real AudioWorklet, automatic turns, playback, cross-window stop", async () => {
  const { app, page } = await launch();
  try {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const history: object[] = [];
    let transcriptions = 0;
    let syntheses = 0;
    const turnVoices: { engine: string; voice: string }[] = [];
    await app
      .context()
      .route("**/voice/prepare", (route) =>
        route.fulfill({ json: { ok: true } }),
      );
    await app.context().route("**/voice/transcribe", async (route) => {
      transcriptions++;
      expect(route.request().postDataBuffer()?.length).toBeGreaterThan(10000);
      await route.fulfill({ json: { text: "Давай поговорим о звёздах" } });
    });
    await app
      .context()
      .route("**/messages*", (route) => route.fulfill({ json: history }));
    await app.context().route("**/chat", async (route) => {
      const body = route.request().postDataJSON();
      expect(body.mode).toBe("conversation");
      const user = {
        id: `u${transcriptions}`,
        role: "user",
        content: body.text,
        created: new Date().toISOString(),
      };
      const assistant = {
        id: `a${transcriptions}`,
        role: "assistant",
        content: "Конечно, что тебя интересует в звёздах?",
        created: new Date().toISOString(),
      };
      history.push(user, assistant);
      await route.fulfill({
        contentType: "text/event-stream",
        body: [
          { type: "user", message: user },
          { type: "delta", text: assistant.content },
          { type: "done", message: assistant },
        ]
          .map((event) => "data: " + JSON.stringify(event) + "\n\n")
          .join(""),
      });
    });
    await app.context().route("**/voice/synthesize", async (route) => {
      syntheses++;
      turnVoices.push(route.request().postDataJSON());
      await route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(
          wav(new Float32Array(syntheses === 1 ? 8000 : 48000), 16000),
        ),
      });
    });
    await startLayoutProbe(page);
    await page
      .getByRole("button", { name: "Начать разговор", exact: true })
      .click();
    await expect(page.locator(".conversation-phase")).toHaveText(
      /Слушаю вас|Слышу вашу фразу/,
      { timeout: 10000 },
    );
    await expect
      .poll(() => syntheses, { timeout: 20000 })
      .toBeGreaterThanOrEqual(1);
    await expect(page.locator(".conversation-phase")).toHaveText("Слушаю вас");
    await expectStableLayout(page);
    await page.screenshot({
      path: "local/screenshots/conversation-fixed-header.png",
    });
    await page.setViewportSize({ width: 820, height: 900 });
    await startLayoutProbe(page);
    await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      const response = await fetch(url + "/settings/speech", {
        method: "PUT",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tts_engine: "qwen3", tts_voice: "serena" }),
      });
      if (!response.ok)
        throw new Error("Could not update voice during conversation");
    });
    await expect(
      page
        .getByText("Конечно, что тебя интересует в звёздах?", { exact: true })
        .first(),
    ).toBeVisible();
    // A second utterance starts without pressing a record/send button.
    await expect
      .poll(() => syntheses, { timeout: 12000 })
      .toBeGreaterThanOrEqual(2);
    expect(turnVoices[1]).toMatchObject({ engine: "qwen3", voice: "serena" });
    await page
      .getByRole("button", { name: "■ Остановить озвучку", exact: true })
      .click();
    await expect(page.locator(".conversation-phase")).toHaveText("Слушаю вас");
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    await expect(
      avatar.getByText("Разговор в другом окне", { exact: true }).first(),
    ).toBeVisible();
    await avatar
      .getByRole("button", { name: "Завершить разговор", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Начать разговор", exact: true }),
    ).toBeVisible();
    await micStopped(page);
    await expectStableLayout(page);
    await expect
      .poll(async () => (await audioStats(page)).context)
      .toBe("closed");
    const stoppedFrames = (await audioStats(page)).frames;
    const stoppedCount = transcriptions;
    await page.waitForTimeout(5500);
    expect(transcriptions).toBe(stoppedCount);
    expect((await audioStats(page)).frames).toBe(stoppedFrames);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: "local/screenshots/conversation.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
});

test("conversation: stopping pending recognition prevents sending its late result", async () => {
  const { app, page } = await launch();
  let pending: Route | undefined;
  try {
    let chats = 0;
    await page.route("**/voice/prepare", (route) =>
      route.fulfill({ json: { ok: true } }),
    );
    await page.route("**/voice/transcribe", (route) => {
      pending = route;
    });
    await page.route("**/chat", (route) => {
      chats++;
      return route.abort();
    });
    await page
      .getByRole("button", { name: "Начать разговор", exact: true })
      .click();
    await expect.poll(() => Boolean(pending), { timeout: 20000 }).toBe(true);
    await page
      .getByRole("button", { name: "Завершить разговор", exact: true })
      .click();
    await micStopped(page);
    await pending!
      .fulfill({
        json: { text: "Этот отменённый запрос не должен уйти в чат" },
      })
      .catch(() => {});
    await page.waitForTimeout(500);
    expect(chats).toBe(0);
  } finally {
    await app.close();
  }
});

test("conversation: another real microphone phrase is retained while a reply is pending", async () => {
  const { app, page } = await launch();
  let first: Route | undefined;
  let transcriptions = 0;
  const chats: string[] = [];
  const history: object[] = [];
  const reply = (text: string, index: number) => {
    const user = {
      id: `queued-u${index}`,
      role: "user",
      content: text,
      created: new Date().toISOString(),
    };
    const assistant = {
      id: `queued-a${index}`,
      role: "assistant",
      content: "Услышала вашу мысль.",
      created: new Date().toISOString(),
    };
    history.push(user, assistant);
    return [
      { type: "user", message: user },
      { type: "delta", text: assistant.content },
      { type: "done", message: assistant },
    ]
      .map((event) => "data: " + JSON.stringify(event) + "\n\n")
      .join("");
  };
  try {
    await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      };
      const settings = await (
        await fetch(url + "/settings", { headers })
      ).json();
      const saved = await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...settings,
          stt_environment: "music",
          conversation_listen_while_thinking: true,
        }),
      });
      if (!saved.ok) throw new Error("Settings were not saved");
    });
    await page.route("**/voice/prepare", (route) =>
      route.fulfill({ json: { ok: true } }),
    );
    await page.route("**/voice/transcribe", (route) => {
      transcriptions++;
      return route.fulfill({
        json: {
          text: transcriptions === 1 ? "Первая мысль" : "Ещё одна мысль",
        },
      });
    });
    await page.route("**/messages*", (route) =>
      route.fulfill({ json: history }),
    );
    await page.route("**/voice/synthesize", (route) =>
      route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(8000), 16000)),
      }),
    );
    await page.route("**/chat", (route) => {
      chats.push(route.request().postDataJSON().text);
      if (chats.length === 1) {
        first = route;
        return;
      }
      return route.fulfill({
        contentType: "text/event-stream",
        body: reply(chats.at(-1)!, chats.length),
      });
    });
    await page
      .getByRole("button", { name: "Начать разговор", exact: true })
      .click();
    await expect(page.locator(".conversation-phase")).toHaveText(
      "Измеряю фон · помолчите",
      { timeout: 10000 },
    );
    await expect.poll(() => !!first, { timeout: 15000 }).toBe(true);
    await expect(page.locator(".conversation-phase")).toHaveText(
      "Думаю · слушаю вас",
    );
    await expect(page.locator(".conversation-phase")).toHaveText(
      "Следующая фраза в очереди",
      { timeout: 12000 },
    );
    expect(transcriptions).toBe(1);
    expect(chats).toEqual(["Первая мысль"]);
    await first!.fulfill({
      contentType: "text/event-stream",
      body: reply(chats[0], 1),
    });
    await expect.poll(() => chats.length, { timeout: 10000 }).toBe(2);
    expect(chats).toEqual(["Первая мысль", "Ещё одна мысль"]);
    await page
      .getByRole("button", { name: "Завершить разговор", exact: true })
      .click();
    await micStopped(page);
    const stopped = transcriptions;
    await page.waitForTimeout(5500);
    expect(transcriptions).toBe(stopped);
    await page.screenshot({ path: "local/screenshots/conversation-queue.png" });
  } finally {
    await app.close();
  }
});

test("conversation: missing voice component stops before acquiring the microphone", async () => {
  const { app, page } = await launch();
  try {
    await page.route("**/voice/prepare", (route) =>
      route.fulfill({
        status: 400,
        json: { detail: "Сначала скачайте Whisper" },
      }),
    );
    await page
      .getByRole("button", { name: "Начать разговор", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "Сначала скачайте Whisper",
    );
    await expect(
      page.getByRole("button", { name: "Начать разговор", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { testMicTracks: MediaStreamTrack[] })
            .testMicTracks.length,
      ),
    ).toBe(0);
    expect(
      await page.evaluate(() => window.wiley.conversationState()),
    ).toMatchObject({ active: false });
  } finally {
    await app.close();
  }
});

test("audio devices: selected mic in checks/manual/conversation, selected output for both engines, persistence", async () => {
  const { app, page, data } = await launch();
  let inputId = "";
  let outputId = "";
  try {
    let transcriptions = 0;
    await page.route("**/voice/transcribe", (route) => {
      transcriptions++;
      return route.fulfill({ json: { text: "Проверка микрофона" } });
    });
    // Optional models are not needed to verify routing through the UI.
    await page.route("**/voice", (route) =>
      route.fulfill({
        json: {
          available: true,
          installed_stt: ["small"],
          silero_installed: true,
          silero_v5_6_installed: true,
          piper_available: true,
          qwen3_available: true,
          qwen3_installed: true,
          qwen3_voices: [
            { name: "serena", language: "Serena · мягкий женский" },
          ],
          piper_voices: [
            { name: "irina", label: "Ирина · женский", installed: true },
          ],
          tts_available: true,
          voices: [{ name: "Test SAPI", language: "ru" }],
        },
      }),
    );
    await page.reload();
    await page.getByRole("button", { name: "⚙ Настройки" }).click();
    await page
      .getByRole("tab", { name: "Микрофон и разговор", exact: true })
      .click();
    const mic = page.getByLabel("Микрофон", { exact: true });
    const speaker = page.getByLabel("Динамик / наушники", { exact: true });
    await expect(mic).toBeVisible();
    // Initial permission may conceal device IDs. A user initiated check unlocks labels.
    await page
      .getByRole("button", { name: "Проверить микрофон", exact: true })
      .click();
    await expect(
      page.getByRole("meter", { name: "Уровень микрофона" }),
    ).toBeVisible();
    await expect.poll(() => mic.locator("option").count()).toBeGreaterThan(1);
    await page
      .getByRole("button", { name: "Остановить проверку", exact: true })
      .click();
    await micStopped(page);
    inputId =
      (await mic
        .locator('option[value]:not([value=""]):not([value="communications"])')
        .first()
        .getAttribute("value")) || "";
    outputId =
      (await speaker
        .locator('option[value]:not([value=""]):not([value="communications"])')
        .first()
        .getAttribute("value")) || "";
    expect(inputId).not.toBe("");
    expect(outputId).not.toBe("");
    await mic.selectOption(inputId);
    await speaker.selectOption(outputId);
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await page
      .getByRole("button", { name: "Проверить микрофон", exact: true })
      .click();
    await expect(
      page.getByRole("meter", { name: "Уровень микрофона" }),
    ).toBeVisible();
    await expect
      .poll(() =>
        page
          .getByRole("meter")
          .evaluate((meter: HTMLMeterElement) => meter.value),
      )
      .toBeGreaterThan(0);
    await page
      .getByRole("button", { name: "Остановить проверку", exact: true })
      .click();
    await micStopped(page, 2);
    expect(transcriptions).toBe(0);
    expect(
      await page.evaluate(
        () =>
          (
            window as unknown as { testMicTracks: MediaStreamTrack[] }
          ).testMicTracks[1].getConstraints().deviceId,
      ),
    ).toEqual({ exact: inputId });

    await page.evaluate(() => {
      const ids: string[] = [];
      Object.assign(window, { testOutputIds: ids });
      const original = HTMLMediaElement.prototype.setSinkId;
      HTMLMediaElement.prototype.setSinkId = function (id) {
        ids.push(id);
        return original.call(this, id);
      };
    });
    await page
      .getByRole("button", { name: "Проверить динамик", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Проверить динамик", exact: true }),
    ).toBeEnabled();
    const engines: string[] = [];
    const selectedVoices: string[] = [];
    const devices: string[] = [];
    await page.route("**/voice/synthesize", (route) => {
      engines.push(route.request().postDataJSON().engine);
      selectedVoices.push(route.request().postDataJSON().voice);
      devices.push(route.request().postDataJSON().device);
      return route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(4000), 16000)),
      });
    });
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    await page
      .getByRole("button", { name: "♪ Прослушать голос", exact: true })
      .click();
    await expect.poll(() => engines).toEqual(["silero"]);
    await page
      .getByLabel("Движок озвучки", { exact: true })
      .selectOption("sapi");
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { testOutputIds: string[] }).testOutputIds
              .length,
        ),
      )
      .toBe(2);
    // Wait until the first playback has ended before testing the second engine.
    await page.waitForTimeout(350);
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    await page
      .getByRole("button", { name: "♪ Прослушать голос", exact: true })
      .click();
    await expect.poll(() => engines).toEqual(["silero", "sapi"]);
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { testOutputIds: string[] }).testOutputIds,
        ),
      )
      .toEqual([outputId, outputId, outputId]);
    await page.waitForTimeout(350);
    await page.screenshot({
      path: "local/screenshots/audio-devices.png",
      fullPage: true,
    });
    for (const [engine, voiceName] of [
      ["piper", "irina"],
      ["silero_v5_6", "baya"],
    ]) {
      await page
        .getByLabel("Движок озвучки", { exact: true })
        .selectOption(engine);
      await page
        .getByLabel("Голос ассистента", { exact: true })
        .selectOption(voiceName);
      await page
        .getByRole("button", { name: "♪ Прослушать голос", exact: true })
        .click();
      await expect.poll(() => engines.at(-1)).toBe(engine);
      await expect.poll(() => selectedVoices.at(-1)).toBe(voiceName);
      await expect
        .poll(() =>
          page.evaluate(
            () =>
              (window as unknown as { testOutputIds: string[] }).testOutputIds
                .length,
          ),
        )
        .toBe(engine === "piper" ? 4 : 5);
      await expect(
        page.getByRole("button", { name: "■ Остановить озвучку", exact: true }),
      ).toBeHidden();
    }
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { testOutputIds: string[] }).testOutputIds,
        ),
      )
      .toEqual(Array(5).fill(outputId));
    await page
      .getByLabel("Движок озвучки", { exact: true })
      .selectOption("qwen3");
    await page
      .getByLabel("Голос ассистента", { exact: true })
      .selectOption("serena");
    await page
      .getByLabel("Устройство Qwen3-TTS", { exact: true })
      .selectOption("cpu");
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    await page
      .getByRole("button", { name: "♪ Прослушать голос", exact: true })
      .click();
    await expect.poll(() => engines.at(-1)).toBe("qwen3");
    await expect.poll(() => selectedVoices.at(-1)).toBe("serena");
    await expect.poll(() => devices.at(-1)).toBe("cpu");
    await expect(
      page.getByRole("button", { name: "■ Остановить озвучку", exact: true }),
    ).toBeHidden();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await page.getByRole("button", { name: "◈ Общение" }).click();
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
      "Проверка микрофона",
    );
    expect(
      await page.evaluate(
        () =>
          (
            window as unknown as { testMicTracks: MediaStreamTrack[] }
          ).testMicTracks[2].getConstraints().deviceId,
      ),
    ).toEqual({ exact: inputId });
    await page.route("**/voice/prepare", (route) =>
      route.fulfill({ json: { ok: true } }),
    );
    await page
      .getByRole("button", { name: "Начать разговор", exact: true })
      .click();
    await expect(page.locator(".conversation-phase")).toHaveText(
      /Слушаю вас|Слышу вашу фразу/,
    );
    expect(
      await page.evaluate(
        () =>
          (
            window as unknown as { testMicTracks: MediaStreamTrack[] }
          ).testMicTracks[3].getConstraints().deviceId,
      ),
    ).toEqual({ exact: inputId });
    await page
      .getByRole("button", { name: "Завершить разговор", exact: true })
      .click();
    await expect
      .poll(() =>
        page.evaluate(() =>
          (
            window as unknown as { testMicTracks: MediaStreamTrack[] }
          ).testMicTracks.map((track) => track.readyState),
        ),
      )
      .toEqual(["ended", "ended", "ended", "ended"]);
    await expect(page.getByRole("alert")).toHaveCount(0);
  } finally {
    await app.close();
  }
  const again = await launch(data);
  try {
    await again.page.getByRole("button", { name: "⚙ Настройки" }).click();
    await expect(
      again.page.getByLabel("Микрофон", { exact: true }),
    ).toHaveValue(inputId);
    await expect(
      again.page.getByLabel("Динамик / наушники", { exact: true }),
    ).toHaveValue(outputId);
    await expect(
      again.page.getByLabel("Движок озвучки", { exact: true }),
    ).toHaveValue("qwen3");
    await expect(
      again.page.getByLabel("Устройство Qwen3-TTS", { exact: true }),
    ).toHaveValue("cpu");
  } finally {
    await again.app.close();
  }
});

test("speech can be stopped during synthesis and playback, with Escape and from the avatar", async ({}, testInfo) => {
  const { app, page } = await launch();
  try {
    const cancelled: string[] = [];
    let synthesisId = "";
    let release: () => void = () => {};
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    let count = 0;
    const sound = Buffer.from(wav(new Float32Array(16000 * 60), 16000));
    await app.context().route("**/voice/stop", async (route) => {
      cancelled.push(route.request().postDataJSON()?.request_id);
      await route.fulfill({ json: { ok: true } });
    });
    await app.context().route("**/voice/synthesize", async (route) => {
      count++;
      if (count === 1) {
        synthesisId = route.request().postDataJSON().request_id;
        await waiting;
      }
      await route
        .fulfill({ contentType: "audio/wav", body: sound })
        .catch(() => {});
    });
    await page.evaluate(() => {
      const audios: HTMLAudioElement[] = [];
      Object.assign(window, { testTtsAudios: audios });
      const AudioClass = window.Audio;
      window.Audio = class extends AudioClass {
        constructor(src?: string) {
          super(src);
          audios.push(this);
        }
      };
    });
    await page.getByRole("button", { name: "⚙ Настройки" }).click();
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    const preview = page.getByRole("button", {
      name: "♪ Прослушать голос",
      exact: true,
    });
    const stop = page.getByRole("button", {
      name: "■ Остановить озвучку",
      exact: true,
    });
    await preview.click();
    await expect.poll(() => synthesisId).not.toBe("");
    await expect(stop).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(stop).toBeHidden();
    await expect.poll(() => cancelled).toContain(synthesisId);
    release();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { testTtsAudios: HTMLAudioElement[] })
              .testTtsAudios.length,
        ),
      )
      .toBe(0);

    await preview.click();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { testTtsAudios: HTMLAudioElement[] })
              .testTtsAudios[0]?.paused,
        ),
      )
      .toBe(false);
    await stop.click();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { testTtsAudios: HTMLAudioElement[] })
              .testTtsAudios[0]?.paused,
        ),
      )
      .toBe(true);
    await expect
      .poll(() =>
        page.evaluate(() =>
          (
            window as unknown as { testTtsAudios: HTMLAudioElement[] }
          ).testTtsAudios[0]?.getAttribute("src"),
        ),
      )
      .toBe(null);

    await preview.click();
    await expect(stop).toBeVisible();
    await testInfo.attach("speech-stop-settings", {
      body: await page.screenshot({
        path: "local/screenshots/speech-stop-settings.png",
      }),
      contentType: "image/png",
    });
    // Opening another window mid-playback must recover the speaking state.
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    await expect(
      avatar.getByRole("button", { name: "■ Остановить озвучку", exact: true }),
    ).toBeVisible();
    await testInfo.attach("speech-stop-avatar", {
      body: await avatar.screenshot({
        path: "local/screenshots/speech-stop-avatar.png",
      }),
      contentType: "image/png",
    });
    await avatar
      .getByRole("button", { name: "■ Остановить озвучку", exact: true })
      .click();
    await expect(stop).toBeHidden();
    await expect
      .poll(() =>
        page.evaluate(() =>
          (
            window as unknown as { testTtsAudios: HTMLAudioElement[] }
          ).testTtsAudios.every((a) => a.paused),
        ),
      )
      .toBe(true);
    await expect(page.getByRole("alert")).toBeHidden();
  } finally {
    await app.close();
  }
});
