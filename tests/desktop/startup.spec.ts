import { test, expect, _electron as electron } from "@playwright/test";
import { access, mkdtemp, mkdir, writeFile, readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

const executable = createRequire(import.meta.url)("electron") as string;

test("startup: second launch while Python is loading waits for core, restores one window and preserves data on restart", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-startup-"));
  const hooks = join(data, "python startup hook");
  await mkdir(hooks);
  const gate = join(data, "release-python");
  const seen = join(data, "python-started");
  // Hold a real owned Python process BEFORE core startup. No production delay
  // switches or changes to the user's runtime/data are needed.
  await writeFile(
    join(hooks, "sitecustomize.py"),
    `import os, time\nfrom pathlib import Path\ngate = Path(os.environ['WILEY_TEST_PYTHON_GATE'])\nwith open(os.environ['WILEY_TEST_PYTHON_SEEN'], 'a') as log:\n    log.write('started\\n')\nwhile not gate.exists():\n    time.sleep(0.02)\n`,
    "utf8",
  );
  const env = {
    ...process.env,
    WILEYAI_TEST: "1",
    WILEYAI_DATA_DIR: data,
    PYTHONPATH: hooks,
    WILEY_TEST_PYTHON_GATE: gate,
    WILEY_TEST_PYTHON_SEEN: seen,
  };
  const duplicates: ReturnType<typeof spawn>[] = [];
  const secondLaunch = () => {
    const process = spawn(executable, ["."], {
      env,
      windowsHide: true,
      stdio: "ignore",
    });
    duplicates.push(process);
    return process;
  };
  const opening = electron.launch({
    args: ["--mute-audio", "."],
    env,
    timeout: 45000,
  });
  let app: Awaited<typeof opening> | undefined;
  try {
    await expect
      .poll(() =>
        access(seen).then(
          () => true,
          () => false,
        ),
      )
      .toBe(true);
    const duplicate = secondLaunch();
    app = await opening;
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByText("Запускаю локальное ядро…", { exact: true }),
    ).toBeVisible();
    const state = await page.evaluate(async () => {
      let state = "pending";
      void window.wiley.connection().then(
        (value) => {
          state = value?.url ? "ready" : "missing";
        },
        () => {
          state = "failed";
        },
      );
      await new Promise((resolve) => setTimeout(resolve, 150));
      return state;
    });
    if (state !== "pending")
      await page.screenshot({
        path: "local/screenshots/startup-race-before.png",
      });
    expect(state).toBe("pending");
    await expect(page.getByRole("alert")).toHaveCount(0);
    await writeFile(gate, "continue");
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await expect.poll(() => duplicate.exitCode).toBe(0);
    expect(
      await app.evaluate(
        ({ BrowserWindow }) => BrowserWindow.getAllWindows().length,
      ),
    ).toBe(1);
    expect((await readFile(seen, "utf8")).trim().split("\n")).toHaveLength(2);
    await page.evaluate(async () => {
      const connection = await window.wiley.connection();
      const response = await fetch(connection.url + "/memories", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + connection.token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text: "Проверка повторного запуска" }),
      });
      if (!response.ok) throw new Error("Memory not saved");
    });
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].minimize(),
    );
    const duplicateReady = secondLaunch();
    await expect.poll(() => duplicateReady.exitCode).toBe(0);
    await expect
      .poll(() =>
        app!.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()[0].isMinimized(),
        ),
      )
      .toBe(false);
    expect(
      await app.evaluate(
        ({ BrowserWindow }) => BrowserWindow.getAllWindows().length,
      ),
    ).toBe(1);
    await page.screenshot({ path: "local/screenshots/startup-recovered.png" });
    expect(errors).toEqual([]);
    await app.close();
    app = undefined;
    app = await electron.launch({ args: ["--mute-audio", "."], env });
    const again = await app.firstWindow();
    await expect(
      again.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await again.getByRole("button", { name: "◎ Память", exact: true }).click();
    await expect(
      again.getByText("Проверка повторного запуска", { exact: true }),
    ).toBeVisible();
  } finally {
    await writeFile(gate, "continue");
    app ??= await opening.catch(() => undefined);
    if (app) await app.close();
    for (const process of duplicates)
      if (process.exitCode === null) process.kill();
  }
});

test("startup: invalid IPC reply shows a readable retry screen and cannot reach API requests", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-startup-retry-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const connection = await page.evaluate(() => window.wiley.connection());
    await app.evaluate(({ ipcMain }, connection) => {
      let invalid = true;
      ipcMain.removeHandler("connection");
      ipcMain.handle("connection", () => {
        if (invalid) {
          invalid = false;
          return undefined;
        }
        return connection;
      });
    }, connection);
    let requests = 0;
    await page.route(/http:\/\/127\.0\.0\.1:\d+\/settings$/, (route) => {
      requests++;
      void route.continue();
    });
    await page.reload();
    await expect(
      page.getByRole("heading", {
        name: "Не удалось подключиться к локальному ядру",
      }),
    ).toBeVisible();
    await expect(page.getByRole("alert")).toContainText(
      "Локальное ядро ещё не предоставило подключение",
    );
    expect(requests).toBe(0);
    await page.screenshot({ path: "local/screenshots/startup-retry.png" });
    await page
      .getByRole("button", { name: "Повторить подключение", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    expect(requests).toBeGreaterThan(0);
  } finally {
    await app.close();
  }
});
