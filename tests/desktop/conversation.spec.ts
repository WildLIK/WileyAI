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

async function launch() {
  const data = await mkdtemp(join(tmpdir(), "wileyai-conversation-"));
  const sampleRate = 48000;
  const samples = new Float32Array(sampleRate * 5);
  // The fake microphone repeats: a short tone, then enough silence to end a phrase.
  for (let n = sampleRate; n < sampleRate * 1.8; n++)
    samples[n] = 0.3 * Math.sin((2 * Math.PI * 220 * n) / sampleRate);
  const input = join(data, "microphone.wav");
  await writeFile(input, Buffer.from(wav(samples, sampleRate)));
  const app = await electron.launch({
    args: [
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
  await page.evaluate(() => {
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
  });
  return { app, page };
}

async function micStopped(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as unknown as { testMicTracks: MediaStreamTrack[] }
        ).testMicTracks.map((t) => t.readyState),
      ),
    )
    .toEqual(["ended"]);
}

test("conversation: real AudioWorklet, automatic turns, playback, cross-window stop", async () => {
  const { app, page } = await launch();
  try {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const history: object[] = [];
    let transcriptions = 0;
    let syntheses = 0;
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
      .route("**/messages", (route) => route.fulfill({ json: history }));
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
      await route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(
          wav(new Float32Array(syntheses === 1 ? 8000 : 48000), 16000),
        ),
      });
    });
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
    await expect(
      page
        .getByText("Конечно, что тебя интересует в звёздах?", { exact: true })
        .first(),
    ).toBeVisible();
    // A second utterance starts without pressing a record/send button.
    await expect
      .poll(() => syntheses, { timeout: 12000 })
      .toBeGreaterThanOrEqual(2);
    await page.getByRole("button", { name: "Перебить", exact: true }).click();
    await expect(page.locator(".conversation-phase")).toHaveText("Слушаю вас");
    const opened = app.waitForEvent("window");
    await page.getByRole("button", { name: "◈ Аватар", exact: true }).click();
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
