import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("routines: editor, ordering, validation, access, project scope, window sync and persistence", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-routines-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  const commandPage = (page: Page) =>
    page.getByRole("button", { name: "⌘ Команды" }).click();
  const addSite = async (page: Page, index: number, label: string) => {
    await page
      .getByRole("button", { name: "Добавить свой шаг", exact: true })
      .click();
    await page
      .getByLabel("Тип шага " + index, { exact: true })
      .selectOption("url");
    await page
      .getByLabel("Название шага " + index, { exact: true })
      .fill(label);
    await page
      .getByLabel("Путь или адрес шага " + index, { exact: true })
      .fill("https://example.com/" + index);
  };
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await commandPage(page);
    await page.getByLabel("Название сценария", { exact: true }).fill("Работа");
    await page
      .getByLabel("Готовое действие", { exact: true })
      .selectOption({ label: "Сайт · гитхаб" });
    await page
      .getByRole("button", { name: "Добавить шаг", exact: true })
      .click();
    await page
      .getByLabel("Название шага 1", { exact: true })
      .fill("Репозиторий");
    await addSite(page, 2, "План проекта");
    await page.getByRole("button", { name: "Шаг 2 выше", exact: true }).click();
    await expect(
      page.getByLabel("Название шага 1", { exact: true }),
    ).toHaveValue("План проекта");
    await page
      .getByRole("button", { name: "Сохранить сценарий", exact: true })
      .click();
    await expect(page.locator(".routine-entry h3")).toHaveText("Работа");
    await expect(page.locator(".routine-entry li strong")).toHaveText([
      "План проекта",
      "Репозиторий",
    ]);
    await page
      .getByRole("button", { name: "Проверить Работа", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText("Проверено шагов: 2");
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await commandPage(second);
    await expect(second.locator(".routine-entry h3")).toHaveText("Работа");
    await page
      .getByRole("button", { name: "Изменить Работа", exact: true })
      .click();
    await page
      .getByLabel("Название сценария", { exact: true })
      .fill("Рабочее место");
    await page
      .getByRole("button", { name: "Убрать шаг 2", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Сохранить сценарий", exact: true })
      .click();
    await expect(second.locator(".routine-entry h3")).toHaveText(
      "Рабочее место",
    );
    await expect(second.locator(".routine-entry li")).toHaveCount(1);
    // Actual core preflight blocks execution; the test never launches a browser.
    await page.getByLabel("Открывать сайты", { exact: true }).uncheck();
    await page
      .getByRole("button", { name: "Сохранить доступ", exact: true })
      .click();
    await expect(
      page.getByText("Доступ сохранён", { exact: true }),
    ).toBeVisible();
    await expect(
      second.getByLabel("Открывать сайты", { exact: true }),
    ).not.toBeChecked();
    await page
      .getByRole("button", { name: "Запустить Рабочее место", exact: true })
      .click();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("Сценарий не запущен");
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("отключено");
    await commandPage(page);
    await page
      .getByRole("button", { name: "Удалить Рабочее место", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Удалить сценарий навсегда", exact: true })
      .click();
    await expect(second.locator(".routine-entry")).toHaveCount(0);
    await page.getByRole("button", { name: "＋ Проект", exact: true }).click();
    await page.getByLabel("Название проекта").fill("Рабочий проект");
    await page
      .getByRole("button", { name: "Создать проект", exact: true })
      .click();
    await commandPage(page);
    await expect(page.locator(".routine-section .scope-label")).toContainText(
      "Рабочий проект",
    );
    await page
      .getByLabel("Название сценария", { exact: true })
      .fill("Проектный старт");
    await addSite(page, 1, "Доска проекта");
    await page
      .getByRole("button", { name: "Сохранить сценарий", exact: true })
      .click();
    await expect(second.locator(".routine-entry h3")).toHaveText(
      "Проектный старт",
    );
    await page.screenshot({
      path: "local/screenshots/routines.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
  try {
    app = await launch();
    const page = await app.firstWindow();
    await commandPage(page);
    await expect(page.locator(".routine-entry h3")).toHaveText(
      "Проектный старт",
    );
    await expect(page.locator(".routine-section .scope-label")).toContainText(
      "Рабочий проект",
    );
    await expect(
      page.getByLabel("Открывать сайты", { exact: true }),
    ).not.toBeChecked();
  } finally {
    await app.close();
  }
});
