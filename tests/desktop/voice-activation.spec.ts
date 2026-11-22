import { test, expect, _electron as electron, type Page } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { wav } from "../../src/voice/speech";

async function profile(page: Page, changes: object) {
  return page.evaluate(async (changes) => {
    const c = await window.wiley.connection();
    const headers = { Authorization: "Bearer " + c.token, "Content-Type": "application/json" };
    const settings = await (await fetch(c.url + "/settings", { headers })).json();
    const result = await fetch(c.url + "/settings", { method: "PUT", headers, body: JSON.stringify({ ...settings, ...changes }) });
    if (!result.ok) throw new Error("Could not save isolated test settings");
    return await result.json();
  }, changes);
}

async function launch(changes: object = {}, dataDir?: string) {
  const data = dataDir || await mkdtemp(join(tmpdir(), "wiley-activation-"));
  const app = await electron.launch({ args: ["--mute-audio", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--use-file-for-fake-audio-capture=" + resolve("tests/fixtures/endpoint/short.wav"), "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  const page = await app.firstWindow(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
  if (!dataDir) await profile(page, { stt_environment: "normal", conversation_vad: "silero", conversation_wake_required: false, conversation_wake_word: "Уайли", conversation_barge_in: false, conversation_listen_while_thinking: true, conversation_smart_turn: false, voice_diagnostics: true, ...changes });
  await page.reload(); await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
  let text = "Расскажи о Луне", stt = 0, chats = 0, tts = 0, playback = 3200, rejected = false;
  await page.route("**/voice/prepare", (route) => route.fulfill({ json: { ok: true } }));
  await page.route("**/voice/transcribe", (route) => { stt++; return route.fulfill({ json: rejected ? { text: "", rejected_reason: "stt_repetitive_transcript", rejected_characters: 452 } : { text } }); });
  await page.route("**/voice/synthesize", (route) => { tts++; return route.fulfill({ contentType: "audio/wav", body: Buffer.from(wav(new Float32Array(playback), 16000)) }); });
  await page.route("**/chat", (route) => {
    chats++; const body = route.request().postDataJSON();
    const message = { id: "activation-" + chats, role: "assistant", content: "Луна — спутник Земли.", created: new Date().toISOString() };
    return route.fulfill({ contentType: "text/event-stream", body: [{ type: "user", message: { ...message, id: "u-" + chats, role: "user", content: body.text } }, { type: "delta", text: message.content }, { type: "done", message }].map((event) => "data: " + JSON.stringify(event) + "\n\n").join("") });
  });
  return { app, page, data, counts: () => ({ stt, chats, tts }), text: (value: string) => { text = value; }, playback: (seconds: number) => { playback = seconds * 16000; }, reject: () => { rejected = true; } };
}

test("normal manual conversation accepts two nameless turns with barge-in enabled while silent", async () => {
  const x = await launch({ conversation_barge_in: true });
  try {
    await x.page.getByRole("button", { name: "Начать разговор", exact: true }).click();
    await expect.poll(() => x.counts().chats, { timeout: 7500 }).toBe(1);
    await expect(x.page.locator(".conversation-phase")).toHaveText("Ожидаю следующую реплику");
    await expect.poll(() => x.counts().chats, { timeout: 7500 }).toBe(2);
    await expect.poll(() => x.counts().tts).toBe(2); expect(x.counts().stt).toBe(2);
    await x.page.getByRole("button", { name: "Завершить разговор", exact: true }).click();
  } finally { await x.app.close(); }
});

for (const scenario of [
  { name: "normal-no-name", music: false, required: false, named: false },
  { name: "normal-user-name-required", music: false, required: true, named: true },
  { name: "normal-user-rejects-missing-name", music: false, required: true, named: false },
  { name: "music-protection-name-off", music: true, required: false, named: false },
  { name: "music-accepts-name-with-toggle-off", music: true, required: false, named: true },
  { name: "music-protection-name-on", music: true, required: true, named: false },
  { name: "music-accepts-name-with-toggle-on", music: true, required: true, named: true },
]) test("manual activation: " + scenario.name, async () => {
  const x = await launch({ stt_environment: scenario.music ? "music" : "normal", conversation_wake_required: scenario.required });
  try {
    if (scenario.named) x.text("Уайли, расскажи о Луне");
    await x.page.getByRole("button", { name: "Начать разговор", exact: true }).click();
    await expect.poll(() => x.counts().stt, { timeout: 8000 }).toBe(1);
    const accepted = scenario.named || (!scenario.music && !scenario.required);
    if (accepted) await expect.poll(() => x.counts().chats).toBe(1);
    else { await expect(x.page.locator('[data-voice-event="activation_rejected"]')).toHaveCount(1); expect(x.counts().chats).toBe(0); }
    await expect(x.page.locator(".conversation-phase")).toHaveText(scenario.music || scenario.required ? "Жду обращения" : "Ожидаю следующую реплику");
    await x.page.getByRole("button", { name: "Завершить разговор", exact: true }).click();
  } finally { await x.app.close(); }
});

test("name is required during actual TTS barge-in, then only one verified replacement is dispatched", async () => {
  const x = await launch({ conversation_barge_in: true }); x.playback(20);
  try {
    await x.page.getByRole("button", { name: "Начать разговор", exact: true }).click();
    await expect.poll(() => x.counts().chats, { timeout: 8000 }).toBe(1);
    x.text("Расскажи о Солнце");
    await expect.poll(() => x.counts().stt, { timeout: 8000 }).toBe(2);
    await expect(x.page.locator('[data-voice-event="activation_rejected"][data-voice-role="barge"]')).toHaveCount(1);
    expect(x.counts().chats).toBe(1);
    x.text("Уайли, расскажи о Юпитере");
    await expect.poll(() => x.counts().chats, { timeout: 8000 }).toBe(2);
    expect(x.counts().stt).toBe(3);
    await x.page.getByRole("button", { name: "Завершить разговор", exact: true }).click();
    expect(x.counts().chats).toBe(2);
  } finally { await x.app.close(); }
});

test("rejected hallucinated STT never reaches activation, chat or TTS", async () => {
  const x = await launch(); x.reject();
  try {
    await x.page.getByRole("button", { name: "Начать разговор", exact: true }).click();
    await expect.poll(() => x.counts().stt, { timeout: 8000 }).toBe(1);
    await expect(x.page.locator('[data-voice-event="stt_rejected"]')).toHaveCount(1);
    await expect(x.page.locator('[data-voice-event="activation_accepted"]')).toHaveCount(0);
    await expect(x.page.locator('[data-voice-event="stt_empty"]')).toHaveCount(0);
    expect(x.counts()).toEqual({ stt: 1, chats: 0, tts: 0 });
    await x.page.getByRole("button", { name: "Завершить разговор", exact: true }).click();
  } finally { await x.app.close(); }
});

test("draft, saved and running policies stay distinct; save/new session/restart apply the correct policy", async () => {
  const x = await launch({ stt_environment: "music" }); let closed = false;
  try {
    const p = x.page;
    const settings = async () => { await p.getByRole("button", { name: "⚙ Настройки", exact: true }).click(); await p.getByRole("tab", { name: "Микрофон и разговор", exact: true }).click(); };
    await settings();
    const panel = p.locator("#settings-panel-microphone"), policy = panel.getByLabel("Действующий режим разговора");
    await panel.getByLabel("Условия записи", { exact: true }).selectOption("normal");
    await panel.getByRole("switch", { name: "Экспериментально: перебивать озвучку обращением по имени", exact: true }).check();
    await expect(policy.locator('[data-voice-policy="saved"]')).toContainText("Музыка и шум");
    await expect(policy.locator('[data-voice-policy="saving"]')).toContainText("несохранённые");
    await p.getByRole("button", { name: "Начать разговор", exact: true }).click();
    await expect(policy.locator('[data-voice-policy="effective"]')).toContainText("Музыка и шум");
    await expect(policy.locator('[data-voice-policy="activation"]')).toContainText("Имя требуется");
    await expect.poll(() => x.counts().stt, { timeout: 8000 }).toBe(1); expect(x.counts().chats).toBe(0);
    await expect(p.getByRole("button", { name: "Сохранить", exact: true })).toBeDisabled();
    await p.getByRole("button", { name: "Завершить разговор", exact: true }).click();
    await p.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(policy.locator('[data-voice-policy="saved"]')).toContainText("Обычная комната");
    await expect(policy.locator('[data-voice-policy="saving"]')).toHaveText("Изменения сохранены.");
    await p.getByRole("button", { name: "Начать разговор", exact: true }).click();
    await expect(policy.locator('[data-voice-policy="activation"]')).toContainText("Имя не требуется");
    await expect.poll(() => x.counts().chats, { timeout: 8000 }).toBe(1);
    await settings();
    await panel.getByRole("switch", { name: "Принимать фразы только после обращения по имени", exact: true }).check();
    await expect(policy.locator('[data-voice-policy="activation"]')).toContainText("Имя не требуется");
    await expect.poll(() => x.counts().chats, { timeout: 8000 }).toBe(2);
    await p.getByRole("button", { name: "Завершить разговор", exact: true }).click();
    await x.app.close(); closed = true;
    const again = await launch({}, x.data);
    try {
      await again.page.getByRole("button", { name: "⚙ Настройки", exact: true }).click(); await again.page.getByRole("tab", { name: "Микрофон и разговор", exact: true }).click();
      await expect(again.page.getByLabel("Условия записи", { exact: true })).toHaveValue("normal");
      await expect(again.page.getByRole("switch", { name: "Принимать фразы только после обращения по имени", exact: true })).not.toBeChecked();
      await expect(again.page.getByRole("switch", { name: "Экспериментально: перебивать озвучку обращением по имени", exact: true })).toBeChecked();
    } finally { await again.app.close(); }
  } finally { if (!closed) await x.app.close(); }
});

test("microphone switches have keyboard semantics, clickable rows, disabled feedback and fit narrow/wide windows", async () => {
  const x = await launch({ ui_theme: "nebula" });
  try {
    const p = x.page; await p.getByRole("button", { name: "⚙ Настройки", exact: true }).click(); await p.getByRole("tab", { name: "Микрофон и разговор", exact: true }).click();
    const panel = p.locator("#settings-panel-microphone");
    await expect(panel.getByRole("switch")).toHaveCount(5);
    const wake = panel.getByRole("switch", { name: "Принимать фразы только после обращения по имени", exact: true });
    await wake.focus(); await p.keyboard.press("Space"); await expect(wake).toBeChecked(); await expect(wake).toBeFocused();
    await wake.locator("..").locator(".settings-switch-copy").click(); await expect(wake).not.toBeChecked();
    for (const width of [1800, 680]) {
      await p.setViewportSize({ width, height: 1000 });
      await p.screenshot({ path: `local/screenshots/voice-activation-switches-${width}.png`, fullPage: true, animations: "disabled" });
      const card = panel.locator(":scope > .card").filter({ has: p.getByRole("heading", { name: "Распознавание и разговор", exact: true }) });
      await card.screenshot({ path: `local/screenshots/voice-activation-card-${width}.png`, animations: "disabled" });
      for (const [state, name] of [["on", "Слушать, пока модель думает"], ["off", "Принимать фразы только после обращения по имени"]]) {
        await panel.getByRole("switch", { name, exact: true }).locator("..").screenshot({ path: `local/screenshots/voice-switch-${state}-${width}.png`, animations: "disabled" });
      }
      const fits = await panel.locator(".settings-switch").evaluateAll((rows) => rows.every((row) => row.scrollWidth <= row.clientWidth + 1 && row.getBoundingClientRect().width > 0));
      expect(fits).toBe(true);
      expect(await panel.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    }
    await p.route("**/voice/endpoint/status", (route) => route.fulfill({ json: { installed: false, available: true, model: "Test Smart Turn", size: 8679182 } }));
    await p.reload(); await p.getByRole("button", { name: "⚙ Настройки", exact: true }).click(); await p.getByRole("tab", { name: "Микрофон и разговор", exact: true }).click();
    let finish: () => Promise<void> = async () => {};
    await p.route("**/voice/endpoint/install", async (route) => { await new Promise<void>((resolve) => { finish = async () => { await route.fulfill({ json: { ok: true } }); resolve(); }; }); });
    await p.getByRole("button", { name: "Скачать веса Smart Turn · 8,3 МиБ", exact: true }).click();
    const smart = p.getByRole("switch", { name: "Проверять завершённость фразы через Smart Turn", exact: true });
    await expect(smart).toBeDisabled(); await expect(smart.locator("..")).toHaveClass(/is-disabled/);
    await finish(); await expect(smart).toBeEnabled();
  } finally { await x.app.close(); }
});

test("failed save is visible and does not claim that the draft profile was applied", async () => {
  const x = await launch();
  try {
    const p = x.page; await p.getByRole("button", { name: "⚙ Настройки", exact: true }).click(); await p.getByRole("tab", { name: "Микрофон и разговор", exact: true }).click();
    await p.getByLabel("Условия записи", { exact: true }).selectOption("music");
    const status = p.locator("#settings-panel-microphone").getByLabel("Действующий режим разговора");
    const rejectSave = async (route: import("@playwright/test").Route) => route.request().method() === "PUT" ? route.fulfill({ status: 503, json: { detail: "Test save unavailable" } }) : route.fallback();
    await p.route("**/settings", rejectSave);
    await p.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(status.locator('[data-voice-policy="saving"]')).toContainText("Не удалось сохранить");
    await expect(status.locator('[data-voice-policy="saved"]')).toContainText("Обычная комната");
    await p.unroute("**/settings", rejectSave);
    await p.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(status.locator('[data-voice-policy="saving"]')).toHaveText("Изменения сохранены.");
    await expect(status.locator('[data-voice-policy="saved"]')).toContainText("Музыка и шум");
  } finally { await x.app.close(); }
});
