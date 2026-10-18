import { _electron as electron } from "@playwright/test";
import { mkdir, writeFile, cp, readFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import testTemp from "./test-temp.cjs";

await testTemp.cleanupAbandonedRuns();
const run = await testTemp.createTestRun();
try {
  await verifyPackaged(run.root);
} finally {
  await testTemp.cleanupTestRun(run);
}

async function verifyPackaged(data) {
  const executable = resolve("local/releases/win-unpacked/WileyAI.exe");
  const version = JSON.parse(
    await readFile(resolve("package.json"), "utf8"),
  ).version;
  const env = {
    ...process.env,
    WILEYAI_TEST: "1",
    WILEYAI_DATA_DIR: data,
    PATH: join(process.env.SystemRoot, "System32"),
    TEMP: data,
    TMP: data,
    TMPDIR: data,
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
    const api = async (route, method = "GET", body) => {
      const response = await fetch(connection.url + route, {
        method,
        headers: {
          Authorization: "Bearer " + connection.token,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) throw new Error(route + ": " + (await response.text()));
      return response.json();
    };
    const health = await api("/health");
    if (health.version !== version || health.stt_available)
      throw new Error("Unexpected base runtime state");
    await api("/memories", "POST", { text: "Standalone restart check" });
    await api("/tasks", "POST", {
      title: "Standalone recurring reminder",
      kind: "reminder",
      due: new Date(Date.now() + 86400000).toISOString(),
      recurrence: {
        rule: "weekly",
        weekdays: [0, 2, 4],
        timezone: "Asia/Yekaterinburg",
      },
    });
    const components = await api("/components");
    if (components.items.some((item) => item.installed))
      throw new Error("Installer contains optional runtimes");
    const audio = await api("/device/audio");
    if (typeof audio.available !== "boolean" || audio.enabled !== true)
      throw new Error("Unexpected Windows audio adapter state");
    if (
      audio.available &&
      (!Number.isInteger(audio.volume) ||
        audio.volume < 0 ||
        audio.volume > 100 ||
        typeof audio.muted !== "boolean")
    )
      throw new Error("Invalid Windows audio level");
    console.log(
      "Standalone Windows audio read OK:",
      audio.available
        ? "native endpoint available"
        : "device unavailable, handled without optional packages",
    );
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
        if (Date.now() > deadline)
          throw new Error("Piper installation timeout");
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
  }
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
    const memories = await (
      await fetch(connection.url + "/memories", { headers })
    ).json();
    if (!memories.some((item) => item.content === "Standalone restart check"))
      throw new Error("Profile did not survive a full restart");
    console.log(
      "Standalone full restart OK: existing profile and connection restored.",
    );
    const tasks = await (
      await fetch(connection.url + "/tasks", { headers })
    ).json();
    const series = tasks.find(
      (item) => item.title === "Standalone recurring reminder",
    );
    if (!series || JSON.parse(series.recurrence).weekdays.join(",") !== "0,2,4")
      throw new Error("Recurring reminder did not survive standalone restart");
    console.log("Standalone recurring schedule preserved after full restart.");
    const selected = await fetch(connection.url + "/chat", {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({
        text: "Найди напоминание Standalone recurring reminder",
        timezone: "Asia/Yekaterinburg",
      }),
    });
    const selection = await selected.text();
    if (!selected.ok || !selection.includes("Выбрана запись"))
      throw new Error("Named task lookup failed in standalone runtime");
    console.log("Standalone named task lookup OK, without a model.");
    if (process.argv.includes("--install-piper")) {
      const voice = await (
        await fetch(connection.url + "/voice", { headers })
      ).json();
      if (!voice.piper_available)
        throw new Error("Installed Piper was not activated after restart");
      if (
        process.argv.includes("--all-native") &&
        (!voice.available || !voice.tts_available)
      )
        throw new Error(
          "Optional Whisper/Torch did not activate after restart",
        );
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
    }
  } finally {
    await next.close();
  }
}
