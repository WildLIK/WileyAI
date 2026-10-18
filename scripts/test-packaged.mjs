import { _electron as electron } from "@playwright/test";
import { mkdir, writeFile, cp, readFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import testTemp from "./test-temp.cjs";
import { spawnSync } from "node:child_process";

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
    const recognition = await api("/settings");
    const music = await api("/music/yandex");
    if (recognition.music_player !== "auto" || music.connected || music.selected)
      throw new Error("Unexpected music connection in a clean packaged profile");
    console.log("Standalone Yandex adapter loaded: no connection or personal player touched.");
    if (
      recognition.stt_environment !== "normal" ||
      recognition.conversation_listen_while_thinking !== true
    )
      throw new Error(
        "Missing conversation/recognition defaults in the packaged runtime",
      );
    await api("/settings", "PUT", {
      ...recognition,
      stt_environment: "music",
      conversation_listen_while_thinking: false,
    });
    const appsBefore = (await api("/aliases")).custom.length;
    const discovered = await api("/applications/scan", "POST");
    if (
      !discovered.supported ||
      Object.keys(discovered.categories).length !== 6 ||
      !Array.isArray(discovered.items)
    )
      throw new Error("Standalone application scan failed");
    if ((await api("/aliases")).custom.length !== appsBefore)
      throw new Error("Read-only application scan changed saved commands");
    console.log(
      `Standalone application scan OK: ${discovered.items.length} known apps; no commands changed.`,
    );
    const cachedApps = await api("/applications");
    if (
      !cachedApps.scanned_at ||
      cachedApps.items.length !== discovered.items.length
    )
      throw new Error("Application scan cache was not saved");
    if (discovered.items.length) {
      const candidate = discovered.items[0];
      const inspection = await fetch(connection.url + "/chat", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + connection.token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text: "Проверь " + candidate.name }),
      });
      const inspected = await inspection.text();
      if (
        !inspection.ok ||
        !inspected.includes("Запуск не выполнялся") ||
        !inspected.includes(candidate.name)
      )
        throw new Error(
          "Native application inspection failed in standalone runtime",
        );
      if (
        !(await api("/actions")).some(
          (item) => item.kind === "app.inspect" && item.status === "found",
        )
      )
        throw new Error("Native application inspection was not audited");
      console.log(
        "Standalone app inspection OK: real cached file found without a model or launch.",
      );
    }
    const helper = join(data, "VerifiedHelper.exe");
    const compiler = join(
      process.env.SystemRoot,
      "System32/WindowsPowerShell/v1.0/powershell.exe",
    );
    const built = spawnSync(
      compiler,
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$p=[Console]::In.ReadToEnd(); Add-Type -TypeDefinition 'class VerifiedHelper { static void Main() { System.Threading.Thread.Sleep(3000); } }' -OutputAssembly $p -OutputType WindowsApplication",
      ],
      {
        input: helper,
        encoding: "utf8",
        windowsHide: true,
        env,
        timeout: 15000,
      },
    );
    if (built.status !== 0)
      throw new Error("Isolated test helper compilation failed");
    await api("/aliases", "POST", {
      name: "проверка процесса",
      kind: "app",
      target: helper,
    });
    const launched = await api("/commands", "POST", {
      text: "Открой проверка процесса",
      dry_run: false,
    });
    const action = (await api("/actions")).find(
      (item) => item.kind === "app" && item.target === helper,
    );
    if (
      !launched.text.includes("PID") ||
      action?.status !== "process_started" ||
      !action.details.pid
    )
      throw new Error("Packaged core did not verify the actual helper process");
    console.log(
      "Standalone native process verification OK: exact EXE and PID recorded.",
    );
    await api("/memories", "POST", { text: "Standalone restart check" });
    await api("/settings/appearance", "PATCH", {
      ui_theme: "nebula",
      ui_motion: "reduced",
    });
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
    await page
      .getByRole("button", { name: "Начать разговор", exact: true })
      .waitFor();
    await page.waitForFunction(
      () =>
        document.documentElement.dataset.theme === "nebula" &&
        document.documentElement.dataset.motion === "reduced",
    );
    const connection = await page.evaluate(() => window.wiley.connection());
    const headers = { Authorization: "Bearer " + connection.token };
    const savedApps = await (
      await fetch(connection.url + "/applications", { headers })
    ).json();
    const recognition = await (
      await fetch(connection.url + "/settings", { headers })
    ).json();
    if (
      recognition.stt_environment !== "music" ||
      recognition.conversation_listen_while_thinking !== false
    )
      throw new Error(
        "Conversation/recognition preferences lost on standalone restart",
      );
    console.log(
      "Standalone recognition and continuous-listening preferences preserved.",
    );
    if (!savedApps.scanned_at || !savedApps.items.length)
      throw new Error("Application scan cache lost on full restart");
    console.log(
      "Standalone application scan cache restored without rescanning.",
    );
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
