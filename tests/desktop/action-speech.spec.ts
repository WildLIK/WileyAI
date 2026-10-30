import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { wav } from "../../src/voice/speech";

test("action display diagnostics never enter the actual TTS request", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-action-speech-"));
  const executable = join(data, "Blender.exe"); await writeFile(executable, "test fixture");
  const pythonPath = [join(process.cwd(), "tests", "fixtures", "action_speech"), process.cwd()].join(delimiter);
  const app = await electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, PYTHONPATH: pythonPath, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  try {
    const page = await app.firstWindow();
    await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    await page.evaluate(async (executable) => {
      const c = await window.wiley.connection();
      const response = await fetch(c.url + "/settings/speech", { method: "PUT", headers: { Authorization: "Bearer " + c.token, "Content-Type": "application/json" }, body: JSON.stringify({ speak_answers: true, action_speech: "brief" }) });
      if (!response.ok) throw new Error(await response.text());
      const alias = await fetch(c.url + "/aliases", { method: "POST", headers: { Authorization: "Bearer " + c.token, "Content-Type": "application/json" }, body: JSON.stringify({ name: "Blender", kind: "app", target: executable }) });
      if (!alias.ok) throw new Error(await alias.text());
    }, executable);
    await page.reload();
    const spoken: string[] = [];
    await page.route("**/voice/synthesize", (route) => {
      spoken.push(route.request().postDataJSON().text);
      return route.fulfill({ contentType: "audio/wav", body: Buffer.from(wav(new Float32Array(8000), 16000)) });
    });
    const recognized = await page.evaluate(async () => {
      const c = await window.wiley.connection();
      const form = new FormData(); form.append("file", new Blob(["test audio"], { type: "audio/wav" }), "utterance.wav");
      const response = await fetch(c.url + "/voice/transcribe", { method: "POST", headers: { Authorization: "Bearer " + c.token }, body: form });
      if (!response.ok) throw new Error(await response.text());
      return (await response.json()).text as string;
    });
    expect(recognized).toBe("Открой Blender");
    const composer = page.getByLabel("Сообщение");
    await composer.fill(recognized); await composer.press("Enter");
    await expect(page.getByText(/PID 30728/)).toBeVisible();
    await expect.poll(() => spoken.map((text) => text.toLocaleLowerCase("ru-RU")), { timeout: 15000 }).toEqual(["запускаю blender."]);
  } finally { await app.close(); }
});
