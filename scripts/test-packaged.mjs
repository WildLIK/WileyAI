import { _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir, writeFile, cp, readFile } from "node:fs/promises";
import { resolve, join } from "node:path";

const data = await mkdtemp(resolve("local", "Standalone test "));
const executable = resolve("local/releases/win-unpacked/WileyAI.exe");
const version = JSON.parse(
  await readFile(resolve("package.json"), "utf8"),
).version;
const env = {
  ...process.env,
  WILEYAI_TEST: "1",
  WILEYAI_DATA_DIR: data,
  PATH: join(process.env.SystemRoot, "System32"),
};
delete env.WILEYAI_PYTHON;
delete env.WILEYAI_DEV;
delete env.PYTHONPATH;
const app = await electron.launch({
  executablePath: executable,
  cwd: data,
  env,
  args: ["--mute-audio"],
});
app.process().stderr.on("data", (block) => process.stderr.write(block));
try {
  const page = await app.firstWindow();
  page.on("pageerror", (error) => console.error("Renderer:", error.message));
  page.on("console", (message) => {
    if (message.type() === "error") console.error("Console:", message.text());
  });
  console.log("Window URL:", page.url());
  await page.waitForLoadState("domcontentloaded");
  console.log(
    "Window content:",
    (await page.locator("body").innerText()).slice(0, 1500),
  );
  await page.getByRole("heading", { name: "Давайте познакомимся" }).waitFor();
  await page
    .getByRole("button", { name: "Настроить позже", exact: true })
    .click();
  await page.getByRole("heading", { name: "Привет, я Уайли." }).waitFor();
  const connection = await page.evaluate(() => window.wiley.connection());
  const api = async (route, method = "GET") => {
    const response = await fetch(connection.url + route, {
      method,
      headers: { Authorization: "Bearer " + connection.token },
    });
    if (!response.ok) throw new Error(route + ": " + (await response.text()));
    return response.json();
  };
  const health = await api("/health");
  if (health.version !== version || health.stt_available)
    throw new Error("Unexpected base runtime state");
  const components = await api("/components");
  if (components.items.some((item) => item.installed))
    throw new Error("Installer contains optional runtimes");
  await page.getByRole("button", { name: "⬡ Модели", exact: true }).click();
  await page
    .getByText("Для локальных моделей сначала установите движок", {
      exact: false,
    })
    .waitFor();
  await mkdir(resolve("local/screenshots"), { recursive: true });
  await page.screenshot({
    path: resolve("local/screenshots/standalone-components.png"),
  });
  console.log(
    "Clean standalone launch OK: no system Python, Node, Git, models or source cwd required.",
  );
  if (process.argv.includes("--install-piper")) {
    await api("/components/piper/install", "POST");
    const deadline = Date.now() + 180000;
    let result;
    do {
      await new Promise((done) => setTimeout(done, 1500));
      result = await api("/components");
      if (Date.now() > deadline) throw new Error("Piper installation timeout");
    } while (result.job?.state === "running");
    if (result.job?.state !== "done") throw new Error(JSON.stringify(result));
    console.log(
      "Piper downloaded and installed through the packaged core and bundled uv.",
    );
    if (process.argv.includes("--all-native")) {
      for (const key of ["whisper", "silero"]) {
        await api(`/components/${key}/install`, "POST");
        const deadline = Date.now() + 240000;
        let result;
        do {
          await new Promise((done) => setTimeout(done, 1500));
          result = await api("/components");
          if (Date.now() > deadline)
            throw new Error(key + " installation timeout");
        } while (result.job?.state === "running");
        if (result.job?.state !== "done")
          throw new Error(JSON.stringify(result));
        console.log("Installed and verified:", key);
      }
    }
    await writeFile(resolve("local/packaged-test-data.txt"), data);
  }
} finally {
  await app.close();
}

if (process.argv.includes("--install-piper")) {
  // Restart with the same data and verify actual native inference, not just files.
  await mkdir(join(data, "models", "piper"), { recursive: true });
  await cp(
    resolve("data/models/piper/irina"),
    join(data, "models", "piper", "irina"),
    { recursive: true },
  );
  const next = await electron.launch({
    executablePath: executable,
    cwd: data,
    env,
    args: ["--mute-audio"],
  });
  try {
    const page = await next.firstWindow();
    await page.getByRole("heading", { name: "Привет, я Уайли." }).waitFor();
    const connection = await page.evaluate(() => window.wiley.connection());
    const headers = { Authorization: "Bearer " + connection.token };
    const voice = await (
      await fetch(connection.url + "/voice", { headers })
    ).json();
    if (!voice.piper_available)
      throw new Error("Installed Piper was not activated after restart");
    if (
      process.argv.includes("--all-native") &&
      (!voice.available || !voice.tts_available)
    )
      throw new Error("Optional Whisper/Torch did not activate after restart");
    const response = await fetch(connection.url + "/voice/synthesize", {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({
        engine: "piper",
        voice: "irina",
        text: "Привет! Проверяю самостоятельную сборку Уайли.",
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    const audio = Buffer.from(await response.arrayBuffer());
    if (audio.subarray(0, 4).toString() !== "RIFF" || audio.length < 10000)
      throw new Error("Invalid speech output");
    await writeFile(resolve("local/packaged-piper-test.wav"), audio);
    console.log(
      "Installed Piper activated after restart and generated real Russian speech:",
      audio.length,
      "bytes.",
    );
  } finally {
    await next.close();
  }
}
