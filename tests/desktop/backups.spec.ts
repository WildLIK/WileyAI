import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function change(page: Page, mode: "seed" | "new" | "stale") {
  await page.evaluate(async (mode) => {
    const connection = await window.wiley.connection();
    const headers = {
      Authorization: "Bearer " + connection.token,
      "Content-Type": "application/json",
    };
    async function api(route: string, method = "GET", data?: unknown) {
      const response = await fetch(connection.url + route, {
        headers,
        method,
        body: data === undefined ? undefined : JSON.stringify(data),
      });
      if (!response.ok) throw new Error("Fixture failed: " + route);
      return response.headers
        .get("content-type")
        ?.startsWith("text/event-stream")
        ? response.text()
        : response.json();
    }
    if (mode === "stale") {
      await api("/notes", "POST", {
        title: "После просмотра",
        content: "Не терять",
      });
      return;
    }
    const config = await api("/settings");
    await api("/settings", "PUT", {
      ...config,
      name: mode === "seed" ? "Уайли из копии" : "Текущее имя",
      model: mode === "seed" ? "archived-model" : "preserved-model",
      base_url: "http://127.0.0.1:1",
    });
    if (mode === "seed") {
      await api("/chat", "POST", {
        text: "Запомни: я предпочитаю примеры на Python",
      });
      await api("/notes", "POST", {
        title: "Идея из копии",
        content: "Собрать ассистента",
      });
      await api("/tasks", "POST", {
        title: "Задача из копии",
        kind: "reminder",
        due: new Date(Date.now() + 3 * 86400000).toISOString(),
      });
      await api("/aliases", "POST", {
        name: "из копии",
        kind: "url",
        target: "https://example.com",
      });
    } else {
      const memories = await api("/memories");
      for (const memory of memories)
        await api("/memories/" + memory.id, "DELETE");
      await api("/memories", "POST", { text: "Новое воспоминание" });
      await api("/memories", "POST", { text: "Ещё один новый факт" });
      const aliases = await api("/aliases");
      for (const alias of aliases.custom)
        await api("/aliases/" + alias.id, "DELETE");
      await api("/aliases", "POST", {
        name: "текущая команда",
        kind: "url",
        target: "https://example.org",
      });
    }
    const channel = new BroadcastChannel("wiley-ui");
    channel.postMessage({ type: "settings" });
    channel.postMessage({ type: "chat-updated" });
    channel.close();
  }, mode);
}

test("backups: native save/open, preview, stale guard, protective copy, all-window updates and persistence", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-backups-"));
  const archive = join(data, "portable.wileyai.json");
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await change(page, "seed");
    await page.getByRole("button", { name: "⚙ Настройки" }).click();
    await page
      .getByRole("tab", { name: "Данные и копии", exact: true })
      .click();
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue(
      "Уайли из копии",
    );
    // Only OS dialogs are replaced. Real native IPC reads/writes real temporary files.
    await app.evaluate(({ dialog }, archive) => {
      dialog.showSaveDialog = async () => ({
        canceled: false,
        filePath: archive,
      });
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [archive],
      });
    }, archive);
    await page
      .getByRole("button", { name: "Сохранить резервную копию", exact: true })
      .click();
    await expect(page.getByRole("status")).toHaveText(
      "Резервная копия сохранена",
    );
    const saved = JSON.parse(await readFile(archive, "utf8"));
    expect(saved.format).toBe("wileyai.backup");
    expect(saved.data.messages).toHaveLength(2);
    expect(saved.data.memories).toHaveLength(1);
    expect(saved.settings).not.toHaveProperty("api_key");
    await change(page, "new");
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const memory = await opened;
    await memory.getByRole("button", { name: "◎ Память" }).click();
    await expect(memory.locator(".memory-entry")).toHaveCount(2);
    const choose = page.getByRole("button", {
      name: "Выбрать копию для восстановления",
    });
    await choose.click();
    await expect(
      page.getByRole("heading", { name: "Проверка перед восстановлением" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Восстановить данные", exact: true }),
    ).toBeDisabled();
    await expect(
      page
        .locator(".backup-preview")
        .getByRole("row")
        .filter({ hasText: "Записи памяти" }),
    ).toHaveText("Записи памяти21");
    await expect(memory.locator(".memory-entry")).toHaveCount(2);
    await change(page, "stale");
    await page.getByLabel("Подтверждаю замену текущих данных копией").check();
    await page
      .getByRole("button", { name: "Восстановить данные", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText("данные изменились");
    await expect(memory.locator(".memory-entry")).toHaveCount(2);
    await page.getByRole("button", { name: "Закрыть ошибку" }).click();
    await choose.click();
    await page.locator(".backup-preview").scrollIntoViewIfNeeded();
    await memory.getByRole("button", { name: "▤ Заметки" }).click();
    await memory
      .locator("article")
      .filter({
        has: memory.getByRole("heading", {
          name: "Идея из копии",
          exact: true,
        }),
      })
      .getByRole("button", { name: "Изменить", exact: true })
      .click();
    await memory
      .getByLabel("Название", { exact: true })
      .fill("Несохранённый старый черновик");
    await page.screenshot({
      path: "local/screenshots/backups-preview.png",
      fullPage: true,
    });
    await page.getByLabel("Подтверждаю замену текущих данных копией").check();
    await page
      .getByRole("button", { name: "Восстановить данные", exact: true })
      .click();
    await expect(page.getByRole("status")).toHaveText(
      "Данные восстановлены. Защитная копия сохранена",
    );
    await expect(page.getByLabel("Имя", { exact: true })).toHaveValue(
      "Уайли из копии",
    );
    await expect(page.getByLabel("Идентификатор модели")).toHaveValue(
      "preserved-model",
    );
    await expect(memory.getByLabel("Название", { exact: true })).toHaveValue(
      "",
    );
    await memory.getByRole("button", { name: "◎ Память" }).click();
    await expect(memory.locator(".memory-entry")).toHaveCount(1);
    await expect(memory.locator(".memory-content")).toHaveText(
      "я предпочитаю примеры на Python",
    );
    const protective = (await readdir(join(data, "backups"))).filter((name) =>
      name.endsWith(".wileyai.json"),
    );
    expect(protective).toHaveLength(1);
    const recovery = JSON.parse(
      await readFile(join(data, "backups", protective[0]), "utf8"),
    );
    expect(recovery.data.memories).toHaveLength(2);
    expect(
      recovery.data.notes.some(
        (note: { title: string }) => note.title === "После просмотра",
      ),
    ).toBe(true);
    expect(recovery.settings.name).toBe("Текущее имя");
    await page.getByRole("button", { name: "⌘ Команды" }).click();
    await expect(page.locator(".alias-row")).toContainText("текущая команда");
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(page.locator(".companion-panel h2")).toHaveText(
      "Уайли из копии",
    );
    await page.getByRole("button", { name: "◷ Задачи" }).click();
    await expect(page.locator(".alias-row")).toContainText("Задача из копии");
    await page.getByRole("button", { name: "▤ Заметки" }).click();
    await expect(
      page.getByRole("heading", { name: "Идея из копии", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "После просмотра", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "⚙ Настройки" }).click();
    await page
      .getByRole("tab", { name: "Данные и копии", exact: true })
      .click();
    // Invalid and cancelled picker results must leave the restored data intact.
    const invalid = join(data, "invalid.json");
    await writeFile(invalid, "not a backup");
    await app.evaluate(({ dialog }, invalid) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [invalid],
      });
    }, invalid);
    await page
      .getByRole("button", { name: "Выбрать копию для восстановления" })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "Не удалось проверить копию",
    );
    await expect(page.locator(".backup-preview")).toHaveCount(0);
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = async () => ({ canceled: true, filePaths: [] });
    });
    await page
      .getByRole("button", { name: "Выбрать копию для восстановления" })
      .click();
    await expect(page.locator(".backup-preview")).toHaveCount(0);
    await page.getByRole("button", { name: "◎ Память" }).click();
    await expect(page.locator(".memory-entry")).toHaveCount(1);
  } finally {
    await app.close();
  }
});
