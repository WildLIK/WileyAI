import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function pending(page: Page) {
  return page.evaluate(async () => {
    const { url, token } = await window.wiley.connection();
    return (
      await fetch(url + "/notifications", {
        headers: { Authorization: "Bearer " + token },
      })
    ).json();
  });
}

test("calendar alerts: form controls, cancelled stale poll, real core delivery to two windows and restart", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-calendar-alerts-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  const notifierPath = join(process.cwd(), "desktop", "notifications.cjs");
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    const times = await page.evaluate(() => {
      const begin = new Date(Date.now() + 10 * 60000);
      begin.setSeconds(0, 0);
      const wall = (value: Date) =>
        new Date(value.getTime() - value.getTimezoneOffset() * 60000)
          .toISOString()
          .slice(0, 16);
      return {
        start: wall(begin),
        end: wall(new Date(begin.getTime() + 30 * 60000)),
      };
    });
    await page.getByLabel("Название события").fill("Встреча с уведомлением");
    await page.getByLabel("Начало", { exact: true }).fill(times.start);
    await page.getByLabel("Окончание", { exact: true }).fill(times.end);
    await expect(
      page.getByLabel("Напомнить о встрече", { exact: true }),
    ).not.toBeChecked();
    await page.getByLabel("Напомнить о встрече", { exact: true }).check();
    await page.getByLabel("За сколько минут до начала").fill("15");
    await page
      .getByRole("button", { name: "Добавить событие", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).toContainText(
      "Напоминание за 15 мин. до начала",
    );
    await expect
      .poll(async () => (await pending(page)).length, { timeout: 15000 })
      .toBe(1);
    const stale = await pending(page);
    await page
      .getByRole("button", {
        name: "Изменить событие «Встреча с уведомлением»",
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Напомнить о встрече", { exact: true }),
    ).toBeChecked();
    await page.getByLabel("Напомнить о встрече", { exact: true }).uncheck();
    await page
      .getByRole("button", { name: "Сохранить событие", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).not.toContainText(
      "Напоминание за",
    );
    const connection = await page.evaluate(() => window.wiley.connection());
    // Exercise the production poller with a stale initial list and a real claim.
    const cancelled = await app.evaluate(
      async (_, { notifierPath, connection, stale }) => {
        const { createNotificationDelivery } = process
          .getBuiltinModule("module")
          .createRequire(notifierPath)(notifierPath);
        const shown: unknown[] = [];
        const poll = createNotificationDelivery({
          connection: () => connection,
          enabled: () => true,
          display: (item: unknown) => shown.push(item),
          fetcher: (url: string, options: RequestInit) =>
            url.endsWith("/notifications")
              ? Promise.resolve(new Response(JSON.stringify(stale)))
              : fetch(url, options),
        });
        await poll();
        return shown;
      },
      { notifierPath, connection, stale },
    );
    expect(cancelled).toEqual([]);
    await page
      .getByRole("button", {
        name: "Изменить событие «Встреча с уведомлением»",
        exact: true,
      })
      .click();
    await page.getByLabel("Напомнить о встрече", { exact: true }).check();
    await page.getByLabel("За сколько минут до начала").fill("15");
    await page
      .getByRole("button", { name: "Сохранить событие", exact: true })
      .click();
    await expect
      .poll(async () => (await pending(page)).length, { timeout: 15000 })
      .toBe(1);
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await second
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await expect(second.locator(".calendar-event")).toContainText(
      "Напоминание за 15 мин.",
    );
    const shown = await app.evaluate(
      async ({ BrowserWindow }, { notifierPath, connection }) => {
        const { createNotificationDelivery } = process
          .getBuiltinModule("module")
          .createRequire(notifierPath)(notifierPath);
        const shown: { kind: string; title: string }[] = [];
        const poll = createNotificationDelivery({
          connection: () => connection,
          enabled: () => true,
          display: (item: { kind: string; title: string }) => {
            shown.push(item);
            for (const window of BrowserWindow.getAllWindows())
              window.webContents.send("reminder", item.title);
          },
        });
        await poll();
        await poll();
        return shown;
      },
      { notifierPath, connection },
    );
    expect(shown).toHaveLength(1);
    expect(shown[0].kind).toBe("calendar");
    for (const window of [page, second])
      await expect(
        window.getByText("Напоминание: " + shown[0].title, { exact: true }),
      ).toBeVisible();
    expect(await pending(page)).toEqual([]);
    // Title-only edits do not re-arm an already delivered reminder.
    await second
      .getByRole("button", {
        name: "Изменить событие «Встреча с уведомлением»",
        exact: true,
      })
      .click();
    await second.getByLabel("Название события").fill("Переименованная встреча");
    await second
      .getByRole("button", { name: "Сохранить событие", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).toContainText(
      "Переименованная встреча",
    );
    await page
      .locator(".calendar-page")
      .evaluate((node) => (node.scrollTop = 0));
    await page.screenshot({
      path: "local/screenshots/calendar-alerts.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("button", { name: "Начать разговор", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).toContainText(
      "Переименованная встреча",
    );
    await page
      .getByRole("button", {
        name: "Изменить событие «Переименованная встреча»",
        exact: true,
      })
      .click();
    await expect(
      page.getByLabel("Напомнить о встрече", { exact: true }),
    ).toBeChecked();
    await expect(page.getByLabel("За сколько минут до начала")).toHaveValue(
      "15",
    );
    expect(await pending(page)).toEqual([]);
  } finally {
    await app.close();
  }
});
