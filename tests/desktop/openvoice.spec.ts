import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { wav } from "../../src/voice/speech";

test("OpenVoice is discoverable, saves its base and target, forwards selection and accepts WAV", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-openvoice-ui-"));
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
    const requests: Record<string, unknown>[] = [];
    await page.route("**/voice/synthesize", async (route) => {
      requests.push(route.request().postDataJSON());
      await route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(800), 16000)),
      });
    });
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    const engine = page.getByLabel("Движок озвучки", { exact: true });
    const base = page.getByLabel("Основа OpenVoice", { exact: true });
    const target = page.getByLabel("Тембр OpenVoice", { exact: true });
    const preview = page.getByRole("button", {
      name: "♪ Прослушать голос",
      exact: true,
    });
    await engine.selectOption("openvoice");
    await expect(base).toBeVisible();
    await expect(target).toHaveValue("mita");
    await base.selectOption("silero_v5_6");
    await target.selectOption("kind-mita");
    await preview.click();
    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0]).toMatchObject({
      engine: "silero_v5_6",
      openvoice_enabled: true,
      openvoice_voice: "kind-mita",
    });
    await expect(preview).toBeEnabled();
    await page
      .getByLabel("WAV-образец OpenVoice", { exact: true })
      .setInputFiles({
        name: "my-character.wav",
        mimeType: "audio/wav",
        buffer: Buffer.from(wav(new Float32Array(32000), 16000)),
      });
    await expect(target).toHaveValue("custom");
    await preview.click();
    await expect.poll(() => requests.length).toBe(2);
    expect(requests[1]).toMatchObject({
      openvoice_enabled: true,
      openvoice_voice: "custom",
    });
    await expect(preview).toBeEnabled();
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Озвучка", exact: true }).click();
    await expect(engine).toHaveValue("openvoice");
    await expect(base).toHaveValue("silero_v5_6");
    await expect(target).toHaveValue("custom");
    await page
      .getByRole("group", {
        name: "OpenVoice · локальное изменение тембра",
        exact: true,
      })
      .screenshot({ path: "local/screenshots/openvoice-settings.png" });
    await engine.selectOption("piper");
    await expect(base).toHaveCount(0);
    await preview.click();
    await expect.poll(() => requests.length).toBe(3);
    expect(requests[2]).toMatchObject({
      engine: "piper",
      openvoice_enabled: false,
    });
    await expect(preview).toBeEnabled();
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
