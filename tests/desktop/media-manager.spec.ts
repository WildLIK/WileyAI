import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { wav } from "../../src/voice/speech";

test("source selection persists and a media command reaches TTS once", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-media-"));
  const pythonPath = [join(process.cwd(), "tests", "fixtures", "media_session"), process.cwd()].join(delimiter);
  const app = await electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, PYTHONPATH: pythonPath, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  try {
    const page = await app.firstWindow();
    await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    await page.getByRole("button", { name: /Команды/ }).first().click();
    await expect(page.getByRole("heading", { name: "Активный проигрыватель" })).toBeVisible();
    const source = page.getByLabel("Источник музыки");
    await expect(source).toHaveValue("auto");
    await source.selectOption("smtc:Spotify");
    await expect(source).toHaveValue("smtc:Spotify");
    const automatic = page.getByRole("checkbox", { name: "Автоматически подключать Яндекс Музыку при запуске через WileyAI" });
    await expect(automatic).toBeEnabled(); await automatic.check(); await expect(automatic).toBeEnabled();
    const autoplay = page.getByRole("checkbox", { name: "Запускать «Мою волну» после открытия Яндекс Музыки (использует специальное подключение)" });
    await expect(autoplay).not.toBeChecked(); await autoplay.check(); await expect(autoplay).toBeEnabled();
    const settings = await page.evaluate(async () => { const c = await window.wiley.connection(); return (await fetch(c.url + "/settings", { headers: { Authorization: "Bearer " + c.token } })).json(); });
    expect(settings.media_source).toBe("smtc:Spotify"); expect(settings.yandex_auto_connect).toBe(true); expect(settings.yandex_auto_play).toBe(true);
    await page.evaluate(async () => { const c = await window.wiley.connection(); await fetch(c.url + "/settings/speech", { method: "PUT", headers: { Authorization: "Bearer " + c.token, "Content-Type": "application/json" }, body: JSON.stringify({ speak_answers: true }) }); });
    await page.reload();
    await page.getByRole("button", { name: /Команды/ }).first().click();
    await expect(page.getByRole("checkbox", { name: "Запускать «Мою волну» после открытия Яндекс Музыки (использует специальное подключение)" })).toBeChecked();
    const spoken: string[] = [];
    await page.route("**/voice/synthesize", (route) => { spoken.push(route.request().postDataJSON().text); return route.fulfill({ contentType: "audio/wav", body: Buffer.from(wav(new Float32Array(4000), 16000)) }); });
    await page.getByRole("button", { name: /Общение/ }).first().click();
    await page.getByLabel("Сообщение").fill("Поставь музыку на паузу"); await page.getByLabel("Сообщение").press("Enter");
    await expect.poll(() => spoken).toEqual(["Поставила на паузу."]);
    const actions = await page.evaluate(async () => { const c = await window.wiley.connection(); return (await fetch(c.url + "/actions", { headers: { Authorization: "Bearer " + c.token } })).json(); });
    const media = actions.filter((row: { kind: string }) => row.kind === "media.session");
    expect(media).toHaveLength(1); expect(media[0].details.result.media.player).toBe("Spotify");
  } finally { await app.close(); }
});
