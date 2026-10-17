import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("calendar: forms, conflicts, chat commands, concurrent windows, project scope and restart", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-calendar-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  let day = "";
  const send = async (page: Page, text: string, expected: string) => {
    await page.getByLabel("Сообщение", { exact: true }).fill(text);
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText(expected);
    await expect(
      page.getByRole("button", { name: "Отправить", exact: true }),
    ).toBeVisible();
  };
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    day = await page.evaluate(() => {
      const date = new Date();
      date.setDate(date.getDate() + 1);
      return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 10);
    });
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await page.getByLabel("Название события").fill("Обзор");
    await page.getByLabel("Начало", { exact: true }).fill(day + "T10:00");
    await page.getByLabel("Окончание", { exact: true }).fill(day + "T10:30");
    await page.getByLabel("Место", { exact: true }).fill("Кабинет 7");
    await page
      .getByRole("button", { name: "Добавить событие", exact: true })
      .click();
    const row = page.locator(".calendar-event").filter({ hasText: "Обзор" });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("Кабинет 7");
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await second
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await expect(second.locator(".calendar-event")).toContainText("Обзор");
    // Editing in one window must not silently overwrite a later edit in another.
    await page
      .getByRole("button", { name: "Изменить событие «Обзор»", exact: true })
      .click();
    await second
      .getByRole("button", { name: "Изменить событие «Обзор»", exact: true })
      .click();
    await second.getByLabel("Название события").fill("Обзор обновлён");
    await second
      .getByRole("button", { name: "Сохранить событие", exact: true })
      .click();
    await expect(row).toContainText("Обзор обновлён");
    await page.getByLabel("Название события").fill("Устаревшая правка");
    await page
      .getByRole("button", { name: "Сохранить событие", exact: true })
      .click();
    await expect(
      page.getByText(
        "Событие изменилось в другом окне. Откройте его в календаре заново",
        { exact: true },
      ),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Закрыть ошибку", exact: true })
      .click();
    await page.getByRole("button", { name: "Отмена", exact: true }).click();
    await page.getByLabel("Название события").fill("Пересечение");
    await page.getByLabel("Начало", { exact: true }).fill(day + "T10:15");
    await page.getByLabel("Окончание", { exact: true }).fill(day + "T11:00");
    await page
      .getByRole("button", { name: "Добавить событие", exact: true })
      .click();
    await expect(page.locator(".calendar-conflict")).toHaveCount(2);
    await expect(second.locator(".calendar-conflict")).toHaveCount(2);
    await page
      .locator(".calendar-page")
      .evaluate((node) => (node.scrollTop = 0));
    await page.screenshot({
      path: "local/screenshots/calendar.png",
      fullPage: true,
    });
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    await send(
      page,
      "создай встречу Проверка из чата завтра в 14 на 30 минут",
      "Создала встречу",
    );
    const spoken = second
      .locator(".calendar-event")
      .filter({ hasText: "Проверка из чата" });
    await expect(spoken).toHaveCount(1);
    await expect(spoken).toContainText("14:00");
    await send(page, "перенеси встречу на 15", "Перенесла встречу");
    await expect(spoken).toContainText("15:30");
    await send(page, "покажи расписание завтра", "Обзор обновлён");
    await send(page, "отмени встречу", "Удалила событие");
    await expect(spoken).toHaveCount(0);
    await page.getByRole("button", { name: "＋ Проект", exact: true }).click();
    await page.getByLabel("Название проекта").fill("Проект календаря");
    await page
      .getByRole("button", { name: "Создать проект", exact: true })
      .click();
    await expect(page.locator(".chat-toolbar small")).toContainText(
      "Проект календаря",
    );
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await expect(
      page.getByText("Календарь проекта «Проект календаря»", { exact: false }),
    ).toBeVisible();
    await expect(page.locator(".calendar-event")).toHaveCount(0);
    // Active chat selection is shared across windows; returning to the general
    // chat restores its calendar without copying project events into it.
    await expect(second.locator(".calendar-event")).toHaveCount(0);
    await second
      .locator(".chat-list-row")
      .filter({ hasText: "создай встречу Проверка из чата" })
      .locator(".chat-select")
      .click();
    await second
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await expect(second.locator(".calendar-event")).toHaveCount(2);
    await second
      .getByRole("button", {
        name: "Удалить событие «Пересечение»",
        exact: true,
      })
      .click();
    await expect(second.locator(".calendar-event")).toHaveCount(1);
    await expect(second.locator(".calendar-conflict")).toHaveCount(0);
    await app.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find(
        (item) =>
          !item.webContents.getURL().includes("view=settings") &&
          !item.webContents.getURL().includes("view=avatar"),
      );
      if (!window) throw new Error("Main window not found");
      window.setSize(930, 780);
    });
    expect(
      await page
        .locator(".calendar-page")
        .evaluate((node) => node.scrollWidth <= node.clientWidth),
    ).toBe(true);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("button", { name: "Начать разговор", exact: true }),
    ).toBeVisible();
    const state = await page.evaluate(async (day) => {
      const { url, token } = await window.wiley.connection();
      const headers = { Authorization: "Bearer " + token };
      const chats = await (
        await fetch(url + "/conversations", { headers })
      ).json();
      const general = chats.find(
        (item: { project_id: string | null }) => !item.project_id,
      );
      const params = new URLSearchParams({
        start: new Date(day + "T00:00").toISOString(),
        end: new Date(day + "T23:59").toISOString(),
        conversation_id: general.id,
      });
      return (
        await fetch(url + "/calendar/events?" + params, { headers })
      ).json();
    }, day);
    expect(state.total).toBe(1);
    expect(state.events[0].title).toBe("Обзор обновлён");
  } finally {
    await app.close();
  }
});
