import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir, symlink, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

test("live Qwen: synthesis through Electron and the real core uses the isolated runtime", async () => {
  test.skip(
    process.env.WILEYAI_QWEN_TESTS !== "1",
    "Requires the isolated Qwen runtime and installed weights",
  );
  test.setTimeout(180000);
  const data = await mkdtemp(join(tmpdir(), "wiley-qwen-live-"));
  await mkdir(join(data, "models"));
  await symlink(
    resolve("data/models/qwen3-tts"),
    join(data, "models/qwen3-tts"),
    "junction",
  );
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.getByRole("button", { name: "⚙ Настройки" }).click();
    await page
      .getByLabel("Движок озвучки", { exact: true })
      .selectOption("qwen3");
    await page
      .getByLabel("Голос ассистента", { exact: true })
      .selectOption("serena");
    await page
      .getByLabel("Устройство Qwen3-TTS", { exact: true })
      .selectOption(process.env.WILEYAI_QWEN_DEVICE || "auto");
    await page.evaluate(() => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        if (String(args[0]).endsWith("/voice/synthesize")) {
          const bytes = await response.clone().arrayBuffer();
          const prefix = new TextDecoder().decode(bytes.slice(0, 12));
          Object.assign(window, {
            qwenResult: {
              status: response.status,
              device: response.headers.get("X-Wiley-TTS-Device"),
              bytes: bytes.byteLength,
              prefix,
              error: response.ok ? "" : new TextDecoder().decode(bytes),
            },
          });
        }
        return response;
      };
    });
    await page
      .getByRole("button", { name: "♪ Прослушать голос", exact: true })
      .click();
    await expect
      .poll(
        () =>
          page.evaluate(
            () => (window as unknown as { qwenResult?: unknown }).qwenResult,
          ),
        { timeout: 150000 },
      )
      .toBeTruthy();
    const result = await page.evaluate(
      () =>
        (
          window as unknown as {
            qwenResult: {
              status: number;
              device: string;
              bytes: number;
              prefix: string;
              error: string;
            };
          }
        ).qwenResult,
    );
    if (result.status !== 200) {
      const diagnostic = await readFile(
        join(data, "logs/qwen-error.json"),
        "utf8",
      ).catch(() => "No worker log");
      throw new Error(result.error + "\n" + diagnostic);
    }
    expect(result.prefix.slice(0, 4)).toBe("RIFF");
    expect(result.prefix.slice(8, 12)).toBe("WAVE");
    expect(result.bytes).toBeGreaterThan(10000);
    expect(["cpu", "cuda"]).toContain(result.device);
    await expect(
      page.getByText(
        result.device === "cpu"
          ? "Qwen3-TTS: озвучка подготовлена на CPU"
          : "Qwen3-TTS: озвучка подготовлена на видеокарте",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "■ Остановить озвучку", exact: true }),
    ).toBeHidden({ timeout: 30000 });
    await expect(page.getByRole("alert")).toBeHidden();
  } finally {
    await app.close();
  }
});
