import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("weather header: saved consent, navigation, refresh, failure and responsive layout", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-weather-header-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let requests = 0,
      fail = false;
    await page.route("**/weather/current", (route) => {
      requests++;
      return route.fulfill(
        fail
          ? { status: 502, json: { detail: "Погодный сервис недоступен" } }
          : {
              json: {
                place: "Москва, Россия",
                timezone: "Europe/Moscow",
                checked_at: "2026-10-21T20:30:00Z",
                current: {
                  temperature: -3.5,
                  feels_like: -7,
                  condition: "небольшой снег",
                  time: "2026-10-21T23:30",
                },
              },
            },
      );
    });
    await page.clock.install({ time: new Date("2026-10-21T20:59:00Z") });
    const header = page.getByRole("region", {
      name: "Погода в верхней панели",
    });
    await expect(header).toContainText("Настроить");
    expect(requests).toBe(0);
    await header.getByRole("button").click();
    await expect(
      page.getByRole("tab", { name: "Поиск", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    const city = page.getByLabel("Город для погоды", { exact: true });
    const consent = page.getByLabel("Получать погоду через Open-Meteo", {
      exact: true,
    });
    const save = page.getByRole("button", { name: "Сохранить", exact: true });
    await expect(city).toHaveAttribute("placeholder", "Москва, Россия");
    await city.fill("Москва, Россия");
    await consent.check();
    // An unsaved form must not grant network consent or change the header city.
    await expect(header).toContainText("Настроить");
    expect(requests).toBe(0);
    await save.click();
    await expect(header).toContainText("-3,5°C");
    await expect(header).toContainText("Ощущается -7°C");
    await expect(header.locator("svg")).toHaveAttribute(
      "data-weather-icon",
      "snow",
    );
    await expect(header.locator("time")).toContainText("21 окт.");
    expect(requests).toBe(1);
    await city.fill("Санкт-Петербург, Россия");
    await expect(header.getByRole("button")).toHaveAttribute(
      "title",
      /Москва, Россия/,
    );
    expect(requests).toBe(1);
    await city.fill("Москва, Россия");
    const nav = page.getByRole("navigation");
    for (const label of ["▦ Календарь", "✉ Почта", "➤ Telegram", "◈ Общение"]) {
      await nav.getByRole("button", { name: label, exact: true }).click();
      await expect(header).toContainText("-3,5°C");
    }
    expect(requests).toBe(1);
    // The date follows the city's midnight, not the computer's time zone.
    await page.clock.fastForward(2 * 60000);
    await expect(header.locator("time")).toContainText("22 окт.");
    expect(requests).toBe(1);
    await page.clock.fastForward(29 * 60000);
    await expect.poll(() => requests).toBe(2);
    await expect(header).toHaveAttribute("data-unavailable", "false");
    fail = true;
    await page.clock.fastForward(31 * 60000);
    await expect(header).toHaveAttribute("data-unavailable", "true");
    await expect(header).toContainText("нет обновления");
    await expect(header).toContainText("-3,5°C");
    await mkdir("local/review", { recursive: true });
    for (const theme of ["nebula", "aurora"]) {
      // Only visual tokens change here; there is no account or setting mutation.
      await page.locator("html").evaluate((element, value) => {
        element.dataset.theme = value;
      }, theme);
      for (const width of [1920, 1280, 760]) {
        await page.setViewportSize({ width, height: 900 });
        const top = page.locator(".topbar");
        await expect(header).toBeVisible();
        const bounds = await top.boundingBox();
        for (const control of [
          header,
          page.getByRole("button", { name: "Открыть поиск", exact: true }),
          page
            .locator(".global-controls .conversation-control > button")
            .first(),
        ]) {
          const box = await control.boundingBox();
          expect(box!.x).toBeGreaterThanOrEqual(bounds!.x);
          expect(box!.x + box!.width).toBeLessThanOrEqual(
            bounds!.x + bounds!.width + 1,
          );
          expect(box!.y + box!.height).toBeLessThanOrEqual(
            bounds!.y + bounds!.height + 1,
          );
        }
        expect(
          await top.evaluate(
            (element) => element.scrollWidth <= element.clientWidth,
          ),
        ).toBe(true);
        await top.screenshot({
          path: `local/review/weather-header-${theme}-${width}.png`,
        });
      }
    }
    // A saved city change drops old readings, including when the new request fails.
    await header.getByRole("button").click();
    await city.fill("Санкт-Петербург, Россия");
    await save.click();
    await expect(header).toContainText("Нет данных");
    await expect(header).not.toContainText("-3,5°C");
    await consent.uncheck();
    await save.click();
    await expect(header).toContainText("Погода");
    const stopped = requests;
    await page.clock.fastForward(61 * 60000);
    expect(requests).toBe(stopped);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
