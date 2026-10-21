import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function api(page: Page, route: string, method = "GET", body?: unknown) {
  return page.evaluate(
    async ({ route, method, body }) => {
      const { url, token } = await window.wiley.connection();
      const response = await fetch(url + route, {
        method,
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new Error("Fixture API " + response.status);
      return response.json();
    },
    { route, method, body },
  );
}

test("weather: explicit preview, another town, seven days, cancellation and saved default", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-weather-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await api(page, "/settings", "PUT", {
      ...(await api(page, "/settings")),
      weather_city: "Москва, Россия",
      weather_enabled: true,
    });
    await page.route("**/weather/current", (route) =>
      route.fulfill({
        json: {
          place: "Москва, Россия",
          timezone: "Europe/Moscow",
          checked_at: new Date().toISOString(),
          current: {
            temperature: 3,
            feels_like: 1,
            condition: "пасмурно",
            time: "2026-10-21T15:30",
          },
        },
      }),
    );
    await page.reload();
    const requests: { city: string; day: number; days: number }[] = [];
    let release: (() => void) | undefined;
    let held: Promise<void> | undefined;
    await page.route("**/weather/preview", async (route) => {
      const body = route.request().postDataJSON();
      requests.push(body);
      if (held) await held;
      const days = Array.from({ length: body.days }, (_, index) => ({
        date: `2026-10-${20 + body.day + index}`,
        low: -7,
        high: -1,
        rain: 70,
        condition: "небольшой снег",
      }));
      await route.fulfill({
        json: {
          place: body.city + ", Россия",
          timezone: "Asia/Yekaterinburg",
          checked_at: "2026-10-20T13:00:00Z",
          current: body.day
            ? null
            : {
                temperature: -3.5,
                feels_like: -7,
                condition: "небольшой снег",
                wind: 4,
                time: "2026-10-20T18:00",
              },
          days,
          sources: [],
        },
      });
    });
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: /Поиск/ }).click();
    const panel = page.getByRole("region", { name: "Погода", exact: true });
    const forecast = panel.getByRole("region", {
      name: "Прогноз погоды",
      exact: true,
    });
    expect(requests).toHaveLength(0);
    await panel
      .getByRole("button", { name: "Проверить погоду", exact: true })
      .click();
    await expect(forecast).toContainText("Москва, Россия");
    await expect(forecast).toContainText("−3,5".replace("−", "-"));
    await panel
      .getByLabel("Другой город для проверки", { exact: true })
      .fill("Санкт-Петербург, Россия");
    await expect(forecast).toHaveCount(0);
    await panel
      .getByLabel("Период прогноза", { exact: true })
      .selectOption({ label: "На неделю" });
    await panel
      .getByRole("button", { name: "Проверить погоду", exact: true })
      .click();
    await expect(forecast).toContainText("Санкт-Петербург");
    await expect(forecast.locator("article")).toHaveCount(7);
    expect((await api(page, "/settings")).weather_city).toBe("Москва, Россия");
    await mkdir("local/review", { recursive: true });
    await forecast.screenshot({ path: "local/review/weather-week.png" });
    held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await panel
      .getByLabel("Другой город для проверки", { exact: true })
      .fill("Москва, Россия");
    await panel
      .getByRole("button", { name: "Проверить погоду", exact: true })
      .click();
    await expect.poll(() => requests.length).toBe(3);
    await panel
      .getByLabel("Другой город для проверки", { exact: true })
      .fill("Санкт-Петербург, Россия");
    release!();
    held = undefined;
    await expect(forecast).toHaveCount(0);
    await panel
      .getByLabel("Период прогноза", { exact: true })
      .selectOption({ label: "Послезавтра" });
    await panel
      .getByRole("button", { name: "Проверить погоду", exact: true })
      .click();
    await expect(forecast).toContainText("Санкт-Петербург");
    await expect(forecast.locator("article")).toHaveCount(1);
    expect(requests.at(-1)?.day).toBe(2);
    expect((await api(page, "/settings")).weather_city).toBe("Москва, Россия");
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: /Поиск/ }).click();
    await expect(
      page.getByLabel("Город для погоды", { exact: true }),
    ).toHaveValue("Москва, Россия");
  } finally {
    await app.close();
  }
});
