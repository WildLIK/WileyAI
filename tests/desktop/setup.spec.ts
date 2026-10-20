import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from "@playwright/test";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const launch = (data: string, packaged = true) =>
  electron.launch({
    args: [
      "--mute-audio",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      ".",
    ],
    env: {
      ...process.env,
      WILEYAI_TEST: "1",
      WILEYAI_PACKAGED: packaged ? "1" : "0",
      WILEYAI_DATA_DIR: data,
    },
  });

test("setup: first launch, model download/cancel, resume after restart, voice/devices and completion", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-setup-first-"));
  let app = await launch(data);
  let installedVoice = false;
  let installedRecognition = false;
  let completeModel = false;
  let job: Record<string, unknown> | null = null;
  let lastConnection: { url: string; token: string };
  async function prepare(current: ElectronApplication) {
    const page = await current.firstWindow();
    page.on("pageerror", (error) =>
      console.error("Setup renderer:", error.message),
    );
    lastConnection = await page.evaluate(() => window.wiley.connection());
    const config = async () =>
      (
        await fetch(lastConnection.url + "/settings", {
          headers: { Authorization: "Bearer " + lastConnection.token },
        })
      ).json();
    await page.route(/http:\/\/127\.0\.0\.1:\d+\/models$/, (route) =>
      route.fulfill({
        json: {
          connected: true,
          installed: completeModel ? [{ id: "qwen3.5:4b", size: 100 }] : [],
          error: null,
        },
      }),
    );
    await page.route(/http:\/\/127\.0\.0\.1:\d+\/components$/, (route) =>
      route.fulfill({
        json: {
          items: ["ollama", "piper", "whisper"].map((id) => ({
            id,
            name: id,
            description: id,
            size: "100 МБ",
            installed: true,
            available: true,
            restart: false,
          })),
          job: null,
        },
      }),
    );
    await page.route(/http:\/\/127\.0\.0\.1:\d+\/voice$/, (route) =>
      route.fulfill({
        json: {
          available: true,
          voices: [],
          installed_stt: installedRecognition ? ["tiny"] : [],
          tts_available: false,
          silero_installed: false,
          silero_v5_6_installed: false,
          qwen3_available: false,
          qwen3_installed: false,
          qwen3_voices: [],
          piper_available: true,
          piper_voices: [
            { name: "irina", label: "Ирина", installed: installedVoice },
          ],
        },
      }),
    );
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/voice\/download$/,
      async (route) => {
        const body = route.request().postDataJSON();
        if (body.model === "piper-irina") installedVoice = true;
        if (body.model === "tiny") installedRecognition = true;
        await route.fulfill({ json: { ok: true } });
      },
    );
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/setup\/check$/,
      async (route) =>
        route.fulfill({
          json: {
            config: await config(),
            brain: {
              connected: true,
              model_available: completeModel,
              models: completeModel ? [{ id: "qwen3.5:4b", size: 100 }] : [],
              error: "",
            },
            speech: {
              synthesis: installedVoice,
              recognition: installedRecognition,
              error: "",
            },
          },
        }),
    );
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/models\/pull$/,
      async (route) => {
        job = {
          id: "setup-download",
          model: route.request().postDataJSON().model,
          status: "running",
          total: 100,
          completed: 25,
          detail: "Загрузка весов",
        };
        await route.fulfill({ json: job });
      },
    );
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/jobs(?:\/.*)?$/,
      async (route) => {
        if (route.request().method() === "DELETE" && job)
          job = { ...job, status: "cancelled", detail: "Загрузка отменена" };
        await route.fulfill({
          json:
            route.request().method() === "DELETE"
              ? { ok: true }
              : job
                ? [job]
                : [],
        });
      },
    );
    await page.reload();
    return page;
  }
  try {
    let page = await prepare(app);
    await expect(
      page.getByRole("heading", { name: "Давайте познакомимся" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Начать настройку" }).click();
    await expect(page.locator(".component-list strong")).toHaveText(["ollama"]);
    await page
      .getByRole("button", { name: "Скачать выбранную модель" })
      .click();
    await expect(
      page.getByRole("progressbar", { name: "Загрузка модели мозга" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Отменить загрузку модели" })
      .click();
    await expect(page.locator(".setup-model-job")).toContainText(
      "Загрузка отменена",
    );
    await page
      .getByRole("button", { name: "Скачать выбранную модель" })
      .click();
    await expect(
      page.getByRole("progressbar", { name: "Загрузка модели мозга" }),
    ).toBeVisible();
    completeModel = true;
    job = {
      ...job!,
      status: "done",
      completed: 100,
      detail: "Модель установлена",
    };
    await expect(
      page.getByText("Подключение доступно, выбранная модель найдена."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Сохранить и продолжить" }).click();
    await page
      .getByLabel("Озвучка ответов", { exact: true })
      .selectOption("piper");
    await page
      .getByLabel("Использовать голосовой ввод и режим разговора")
      .check();
    await expect(page.locator(".component-list strong")).toHaveText([
      "piper",
      "whisper",
    ]);
    await page.setViewportSize({ width: 760, height: 760 });
    expect(
      await page
        .locator(".setup-page")
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    await page.screenshot({ path: "local/screenshots/setup-voice-760.png" });
    await app.close();
    app = await launch(data);
    page = await prepare(app);
    await expect(
      page.getByRole("heading", { name: "Голос и устройства", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Озвучка ответов", { exact: true }),
    ).toHaveValue("piper");
    await expect(
      page.getByLabel("Использовать голосовой ввод и режим разговора"),
    ).toBeChecked();
    await page.getByRole("button", { name: "Скачать голос Ирина" }).click();
    await expect(
      page.getByRole("button", { name: "Голос установлен" }),
    ).toBeDisabled();
    await page
      .getByLabel("Модель распознавания", { exact: true })
      .selectOption("tiny");
    await page
      .getByRole("button", { name: "Скачать модель распознавания" })
      .click();
    let samples = 0;
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/voice\/synthesize$/,
      async (route) => {
        const body = route.request().postDataJSON();
        expect(body.engine).toBe("piper");
        expect(body.voice).toBe("irina");
        expect(Object.keys(body.cloud)).not.toContain("provider");
        samples++;
        const wave = Buffer.alloc(44 + 16000 * 2 * 5);
        wave.write("RIFF");
        wave.writeUInt32LE(wave.length - 8, 4);
        wave.write("WAVEfmt ", 8);
        wave.writeUInt32LE(16, 16);
        wave.writeUInt16LE(1, 20);
        wave.writeUInt16LE(1, 22);
        wave.writeUInt32LE(16000, 24);
        wave.writeUInt32LE(32000, 28);
        wave.writeUInt16LE(2, 32);
        wave.writeUInt16LE(16, 34);
        wave.write("data", 36);
        wave.writeUInt32LE(wave.length - 44, 40);
        await route.fulfill({ contentType: "audio/wav", body: wave });
      },
    );
    await page
      .getByRole("button", { name: "Прослушать выбранный голос" })
      .click();
    await expect.poll(() => samples).toBe(1);
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "Прослушать выбранный голос" }),
    ).toBeVisible({ timeout: 1500 });
    await page.evaluate(() => {
      const original = navigator.mediaDevices.getUserMedia.bind(
        navigator.mediaDevices,
      );
      navigator.mediaDevices.getUserMedia = async (constraints) => {
        const stream = await original(constraints);
        Object.assign(window, { setupTracks: stream.getTracks() });
        return stream;
      };
    });
    await page
      .getByRole("button", { name: "Проверить микрофон", exact: true })
      .click();
    await expect(
      page.getByRole("meter", { name: "Уровень микрофона" }),
    ).toBeVisible();
    // The meter appears while getUserMedia is still acquiring its stream.
    // Wait for real live tracks so the following check exercises their cleanup.
    await expect
      .poll(() =>
        page.evaluate(() => {
          const tracks = (
            window as unknown as { setupTracks?: MediaStreamTrack[] }
          ).setupTracks;
          return Boolean(
            tracks?.length &&
            tracks.every((track) => track.readyState === "live"),
          );
        }),
      )
      .toBe(true);
    await page.getByRole("button", { name: "Сохранить и продолжить" }).click();
    await expect(
      page.getByRole("heading", { name: "Можно начинать общение" }),
    ).toBeVisible();
    expect(
      await page.evaluate(() =>
        (
          window as unknown as { setupTracks: MediaStreamTrack[] }
        ).setupTracks.every((track) => track.readyState === "ended"),
      ),
    ).toBe(true);
    await page.screenshot({ path: "local/screenshots/setup-ready.png" });
    await page
      .getByRole("button", { name: "Начать общение", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const saved = await (
      await fetch(lastConnection!.url + "/settings", {
        headers: { Authorization: "Bearer " + lastConnection!.token },
      })
    ).json();
    expect(saved.tts_engine).toBe("piper");
    expect(saved.tts_voice).toBe("irina");
    expect(saved.stt_model).toBe("tiny");
    expect(saved.speak_answers).toBe(true);
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const state = JSON.parse(await readFile(join(data, "setup.json"), "utf8"));
    expect(state.completed).toBe(true);
    expect(state.active).toBe(false);
  } catch (error) {
    const page = app.windows()[0];
    if (page) {
      console.error(
        "Setup screen:",
        (await page.locator("body").innerText()).slice(-5000),
      );
      await page.screenshot({ path: "local/screenshots/setup-failure.png" });
    }
    throw error;
  } finally {
    await app.close();
  }
});

test("setup: existing installation stays out of the wizard; cloud selection keeps API keys separate", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-setup-cloud-"));
  const app = await launch(data, false);
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Данные и копии", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Открыть мастер настройки" })
      .click();
    await page
      .getByRole("radio", { name: "Через облачный API", exact: false })
      .check();
    await page.getByRole("button", { name: "Начать настройку" }).click();
    await page
      .getByLabel("Ключ API для мозга", { exact: true })
      .fill("TEST_OPENROUTER");
    await page
      .getByLabel("Сервис модели", { exact: true })
      .selectOption("routerai");
    await expect(
      page.getByLabel("Ключ API для мозга", { exact: true }),
    ).toHaveValue("");
    await page
      .getByLabel("Ключ API для мозга", { exact: true })
      .fill("TEST_ROUTERAI");
    await page
      .getByLabel("Модель для общения", { exact: true })
      .fill("test/model");
    const connection = await page.evaluate(() => window.wiley.connection());
    const saved = await (
      await fetch(connection.url + "/settings", {
        headers: { Authorization: "Bearer " + connection.token },
      })
    ).json();
    let submitted: Record<string, unknown> | null = null;
    let cloud = saved;
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/setup\/settings$/,
      async (route) => {
        submitted = route.request().postDataJSON();
        const { api_key: secret, ...fields } = submitted!;
        cloud = { ...saved, ...fields, has_api_key: Boolean(secret) };
        await route.fulfill({ json: cloud });
      },
    );
    await page.route(/http:\/\/127\.0\.0\.1:\d+\/setup\/check$/, (route) =>
      route.fulfill({
        json: {
          config: cloud,
          brain: {
            connected: true,
            model_available: true,
            models: [{ id: "test/model" }],
            error: "",
          },
          speech: { synthesis: false, recognition: false, error: "" },
        },
      }),
    );
    await page
      .getByRole("button", { name: "Сохранить и проверить подключение" })
      .click();
    await expect(
      page.getByLabel("Ключ API для мозга", { exact: true }),
    ).toHaveValue("");
    expect(submitted).toMatchObject({
      api_key: "TEST_ROUTERAI",
      base_url: "https://routerai.ru/api/v1",
      provider: "compatible",
      model: "test/model",
    });
    await page.setViewportSize({ width: 760, height: 760 });
    await page.screenshot({ path: "local/screenshots/setup-cloud-760.png" });
    await page
      .getByRole("button", { name: "Настроить позже", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Настройки ассистента" }),
    ).toBeVisible();
    expect(await readFile(join(data, "setup.json"), "utf8")).not.toContain(
      "TEST_ROUTERAI",
    );
  } finally {
    await app.close();
  }
});
