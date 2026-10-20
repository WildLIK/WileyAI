import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("calendar: civil all-day series survives restart; Google preview requires an explicit selection", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-calendar-google-"));
  const launch = () =>
    electron.launch({
      args: ["--mute-audio", "."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    const today = await page.getByLabel("С даты", { exact: true }).inputValue();
    const tomorrow = await page.evaluate((day) => {
      const date = new Date(day + "T12:00");
      date.setDate(date.getDate() + 1);
      return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 10);
    }, today);
    await page.getByLabel("Название события").fill("Ежедневный обзор");
    await page.getByLabel("Весь день", { exact: true }).check();
    await page.getByLabel("Начало", { exact: true }).fill(today);
    await page
      .getByLabel("До даты (не включая этот день)", { exact: true })
      .fill(tomorrow);
    await page.getByLabel("Повтор", { exact: true }).selectOption("daily");
    await page
      .getByRole("button", { name: "Добавить событие", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).toHaveCount(7);
    await page
      .getByRole("button", {
        name: "Изменить событие «Ежедневный обзор»",
        exact: true,
      })
      .nth(3)
      .click();
    await expect(page.getByLabel("Начало", { exact: true })).toHaveValue(today);
    await expect(
      page.getByText("Изменяется вся серия, начиная с её первого события."),
    ).toBeVisible();
    await page.getByLabel("Название события").fill("Исправленный обзор");
    await page
      .getByRole("button", { name: "Сохранить событие", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).toHaveCount(7);
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).toHaveCount(7);
    await expect(page.locator(".calendar-event").first()).toContainText(
      "Исправленный обзор",
    );
    await page
      .getByRole("button", { name: "Пропустить это вхождение", exact: true })
      .nth(3)
      .click();
    await expect(page.locator(".calendar-event")).toHaveCount(6);
    await page
      .getByRole("button", { name: "Перенести это вхождение", exact: true })
      .nth(2)
      .click();
    await expect(page.getByLabel("Повтор", { exact: true })).toBeDisabled();
    await page.getByLabel("Название события").fill("Только один обзор");
    await page
      .getByRole("button", { name: "Сохранить событие", exact: true })
      .click();
    await expect(page.locator(".calendar-event")).toHaveCount(6);
    await expect(
      page.locator(".calendar-event").filter({ hasText: "Только один обзор" }),
    ).toHaveCount(1);
    const status = {
      configured: true,
      connected: true,
      pending: false,
      error: "",
      binding: {
        calendar_id: "fixture",
        name: "Тестовый календарь",
        timezone: "UTC",
        writable: true,
      },
    };
    const sent: unknown[] = [];
    await page.route("**/calendar/google/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let result: unknown = status;
      if (path.endsWith("/preview"))
        result = {
          ticket: "fixture-ticket",
          rows: [
            {
              id: "row",
              action: "export",
              title: "Предпросмотр серии",
              starts_at: new Date().toISOString(),
              reason: "",
            },
            {
              id: "conflict",
              action: "conflict",
              title: "Обе версии",
              starts_at: new Date().toISOString(),
              reason: "",
            },
          ],
          skipped: [],
        };
      if (path.endsWith("/apply")) {
        sent.push(route.request().postDataJSON());
        result = {
          results: [
            {
              id: "row",
              title: "Предпросмотр серии",
              ok: true,
              message: "Google подтвердил сохранение",
            },
          ],
        };
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(result),
      });
    });
    await page.reload();
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    const google = page.getByRole("region", {
      name: "Подключение Google Calendar",
    });
    await expect(google.getByText(/Аккаунт подключён/)).toBeVisible();
    await google
      .getByRole("button", { name: "Посмотреть изменения за выбранные 7 дней" })
      .click();
    await expect(
      google.getByRole("button", { name: "Перенести выбранные события (0)" }),
    ).toBeDisabled();
    await google
      .getByLabel("Перенести «Предпросмотр серии»")
      .selectOption("local");
    await expect(google.getByLabel("Перенести «Обе версии»")).toHaveValue("");
    await google
      .getByRole("button", { name: "Перенести выбранные события (1)" })
      .click();
    await expect(
      google.getByText("Предпросмотр серии: Google подтвердил сохранение"),
    ).toBeVisible();
    expect(sent).toEqual([
      {
        ticket: "fixture-ticket",
        choices: [{ id: "row", direction: "local" }],
      },
    ]);
    expect(errors).toEqual([]);
    await mkdir(join(process.cwd(), "local", "review"), { recursive: true });
    await page.screenshot({
      path: join(process.cwd(), "local", "review", "calendar-google.png"),
      fullPage: true,
    });
    await page
      .getByRole("button", {
        name: "Удалить событие «Исправленный обзор»",
        exact: true,
      })
      .first()
      .click();
    await expect(page.locator(".calendar-event")).toHaveCount(0);
  } finally {
    await app.close();
  }
});
