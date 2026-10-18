import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function api(page: Page, path: string, method = "GET", body?: unknown) {
  return page.evaluate(
    async ({ path, method, body }) => {
      const { url, token } = await window.wiley.connection();
      const response = await fetch(url + path, {
        method,
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    },
    { path, method, body },
  );
}

test("applications: explicit scan, categories, non-overwriting import and Russian launch names", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-applications-"));
  const specs = [
    ["aimp", "AIMP", "music", "аимп"],
    ["yandex-music", "Яндекс Музыка", "music", "яндекс музыку"],
    ["vlc", "VLC", "video", "влс"],
    ["photoshop", "Adobe Photoshop", "work", "фотошоп"],
    ["telegram", "Telegram", "messengers", "телеграм"],
    ["chrome", "Google Chrome", "browsers", "хром"],
    ["calc", "Калькулятор", "windows", "калькулятор"],
  ];
  const items = await Promise.all(
    specs.map(async ([id, name, category, spoken]) => {
      const target = join(data, id + ".exe");
      await writeFile(target, "test-placeholder");
      return {
        id,
        name,
        category,
        aliases: [spoken],
        target,
        source: "Папка приложения",
      };
    }),
  );
  const original = join(data, "existing-file.txt");
  await writeFile(original, "existing alias");
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  let release = () => {};
  const ready = new Promise<void>((resolve) => {
    release = resolve;
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await api(page, "/aliases", "POST", {
      name: "Telegram",
      kind: "file",
      target: original,
    });
    let scans = 0;
    await page.route("**/applications/scan", async (route) => {
      scans++;
      await ready;
      await route.fulfill({
        json: {
          supported: true,
          items,
          warnings: [],
          categories: {
            music: "Музыка",
            video: "Видео",
            work: "Графика и работа",
            messengers: "Мессенджеры",
            browsers: "Браузеры",
            windows: "Программы Windows",
          },
        },
      });
    });
    await page.getByRole("button", { name: "⌘ Команды", exact: true }).click();
    const panel = page.getByRole("region", {
      name: "Установленные приложения",
      exact: true,
    });
    expect(scans).toBe(0);
    await panel
      .getByRole("button", { name: "Сканировать приложения", exact: true })
      .click();
    await expect(
      panel.getByRole("status", { name: "Ищу установленные приложения…" }),
    ).toBeVisible();
    release();
    const categories = panel.getByRole("group", {
      name: "Категории приложений",
    });
    await expect(categories.getByRole("button")).toHaveCount(6);
    await panel
      .getByRole("article", { name: "AIMP", exact: true })
      .getByRole("button", { name: "Добавить", exact: true })
      .click();
    await expect(
      panel
        .getByRole("article", { name: "AIMP", exact: true })
        .getByRole("button", { name: "Добавлено", exact: true }),
    ).toBeDisabled();
    for (const label of [
      "Видео",
      "Графика и работа",
      "Мессенджеры",
      "Браузеры",
      "Программы Windows",
    ]) {
      await categories
        .getByRole("button", { name: new RegExp("^" + label) })
        .click();
      await expect(panel.locator(".found-application")).toHaveCount(1);
    }
    await categories.getByRole("button", { name: /^Мессенджеры/ }).click();
    await expect(
      panel.getByRole("button", { name: "Имя занято", exact: true }),
    ).toBeDisabled();
    await panel
      .getByRole("button", { name: /^Добавить все найденные/ })
      .click();
    await expect(panel.locator(".application-import-result")).toContainText(
      "Добавлено в команды: 5.",
    );
    const aliases = (await api(page, "/aliases")).custom;
    expect(aliases).toHaveLength(7);
    expect(
      aliases.find((item: { name: string }) => item.name === "telegram").target,
    ).toBe(original);
    for (const item of items.filter((item) => item.id !== "telegram")) {
      const command = await api(page, "/commands", "POST", {
        text: "Открой мне " + item.aliases[0],
        dry_run: true,
      });
      expect(command.kind).toBe("app");
      expect(command.target).toBe(item.target);
    }
    await categories.getByRole("button", { name: /^Музыка/ }).click();
    await expect(
      categories.getByRole("button", { name: /^Музыка/ }),
    ).toHaveAttribute("aria-pressed", "true");
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: "local/screenshots/application-discovery.png",
    });
    await page.setViewportSize({ width: 820, height: 900 });
    await expect(panel).toBeVisible();
    expect(
      await panel.evaluate((node) => node.scrollWidth <= node.clientWidth),
    ).toBe(true);
  } finally {
    release();
    await app.close();
  }
});
