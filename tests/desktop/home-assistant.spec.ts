import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { createServer } from "node:http";
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

test("Home Assistant: real REST fixture, review, verification, navigation and lost reply", async () => {
  const lamp = {
    entity_id: "light.kitchen",
    state: "off",
    attributes: {
      friendly_name: "Кухня",
      supported_color_modes: ["brightness"],
      brightness: 0,
    },
  };
  const sensor = {
    entity_id: "sensor.room",
    state: "22.5",
    attributes: { friendly_name: "Температура", unit_of_measurement: "°C" },
  };
  let writes = 0,
    lose = false;
  let release: (() => void) | undefined;
  let held: Promise<void> | undefined;
  const server = createServer(async (req, res) => {
    if (req.headers.authorization !== "Bearer desktop-home-fixture") {
      res.writeHead(401).end();
      return;
    }
    res.setHeader("Content-Type", "application/json");
    const path = req.url;
    if (req.method === "POST") {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString());
      if (
        !path?.startsWith("/api/services/light/") ||
        body.entity_id !== lamp.entity_id
      ) {
        res.writeHead(400).end("{}");
        return;
      }
      writes++;
      if (held) await held;
      lamp.state = path.endsWith("/turn_off") ? "off" : "on";
      if (typeof body.brightness === "number")
        lamp.attributes.brightness = body.brightness;
      if (lose) {
        req.socket.destroy();
        return;
      }
      res.end("[]");
      return;
    }
    const value =
      path === "/api/"
        ? { message: "API running." }
        : path === "/api/config"
          ? { version: "2026.10.fixture", location_name: "Тестовый дом" }
          : path === "/api/services"
            ? [{ domain: "light", services: { turn_on: {}, turn_off: {} } }]
            : path === "/api/states"
              ? [lamp, sensor]
              : path === "/api/states/light.kitchen"
                ? lamp
                : null;
    res.writeHead(value ? 200 : 404).end(JSON.stringify(value));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("No fixture address");
  const data = await mkdtemp(join(tmpdir(), "wiley-home-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  let page: Page | undefined;
  try {
    page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "⌁ Интеграции", exact: true })
      .click();
    await page
      .getByLabel("Адрес Home Assistant", { exact: true })
      .fill(`http://127.0.0.1:${address.port}`);
    await page
      .getByLabel("Токен Home Assistant", { exact: true })
      .fill("desktop-home-fixture");
    const connected = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/home-assistant/connection" &&
        response.request().method() === "PUT",
    );
    await page
      .getByRole("button", {
        name: "Проверить и сохранить подключение",
        exact: true,
      })
      .click();
    const connection = await connected;
    expect(connection.ok(), await connection.text()).toBe(true);
    await expect(
      page.getByText("Тестовый дом", { exact: false }).first(),
    ).toBeVisible();
    const lampCard = page.locator("article.home-entity").filter({
      has: page.getByLabel("Выбрать Кухня (light.kitchen)", { exact: true }),
    });
    await expect(
      lampCard.getByRole("button", { name: "Включить", exact: true }),
    ).toBeDisabled();
    await page
      .getByLabel("Выбрать Кухня (light.kitchen)", { exact: true })
      .check();
    await page
      .getByLabel(
        "Разрешить управление выбранными устройствами в этом пространстве",
        { exact: true },
      )
      .check();
    await page
      .getByRole("button", { name: "Сохранить доступ (1/100)", exact: true })
      .click();
    await lampCard
      .getByRole("button", { name: "Включить", exact: true })
      .click();
    const review = page.getByRole("region", {
      name: "Подтверждение умного дома",
      exact: true,
    });
    await expect(review).toBeVisible();
    await expect(
      review.getByRole("button", { name: "Подтвердить действие", exact: true }),
    ).toBeDisabled();
    expect(writes).toBe(0);
    await review.getByRole("button", { name: "Отмена", exact: true }).click();
    await page
      .getByLabel("Яркость или скорость, %", { exact: true })
      .fill("30");
    await lampCard
      .getByRole("button", { name: "Яркость 30%", exact: true })
      .click();
    await review
      .getByLabel("Подтверждаю устройство и действие", { exact: true })
      .check();
    await review
      .getByRole("button", { name: "Подтвердить действие", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText("яркость 30%");
    expect(writes).toBe(1);
    expect(lamp.state).toBe("on");
    expect(lamp.attributes.brightness).toBe(76);
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    await page
      .getByRole("button", { name: "⌁ Интеграции", exact: true })
      .click();
    await expect(
      page.getByLabel("Выбрать Кухня (light.kitchen)", { exact: true }),
    ).toBeChecked();
    await expect(page.locator(".page:visible")).toHaveCount(1);
    await expect(
      page.getByRole("heading", {
        name: "Последние действия Home Assistant",
        exact: true,
      }),
    ).toBeVisible();
    lose = true;
    await lampCard
      .getByRole("button", { name: "Выключить", exact: true })
      .click();
    await review
      .getByLabel("Подтверждаю устройство и действие", { exact: true })
      .check();
    await review
      .getByRole("button", { name: "Подтвердить действие", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "пока не подтверждено",
    );
    expect(writes).toBe(2);
    await page
      .getByRole("button", {
        name: "Проверить результат без повтора",
        exact: true,
      })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "подтвердил состояние",
    );
    expect(writes).toBe(2);
    lose = false;
    held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await lampCard
      .getByRole("button", { name: "Включить", exact: true })
      .click();
    await review
      .getByLabel("Подтверждаю устройство и действие", { exact: true })
      .check();
    await review
      .getByRole("button", { name: "Подтвердить действие", exact: true })
      .click();
    await expect.poll(() => writes).toBe(3);
    await page
      .getByRole("button", { name: "▦ Календарь", exact: true })
      .click();
    release!();
    held = undefined;
    await page
      .getByRole("button", { name: "⌁ Интеграции", exact: true })
      .click();
    await expect(
      page
        .locator("article.home-entity")
        .filter({ hasText: "Home Assistant подтвердил состояние" }),
    ).toHaveCount(3);
    expect(writes).toBe(3);
    await mkdir("local/review", { recursive: true });
    await page.locator(".home-page").evaluate((node) => (node.scrollTop = 0));
    await page.screenshot({
      path: "local/review/home-assistant.png",
      fullPage: true,
    });
    await page.reload();
    await page
      .getByRole("button", { name: "⌁ Интеграции", exact: true })
      .click();
    await expect(
      page.getByLabel("Выбрать Кухня (light.kitchen)", { exact: true }),
    ).toBeChecked();
    expect((await api(page, "/home-assistant/actions")).length).toBe(3);
  } finally {
    release?.();
    if (page && !page.isClosed())
      await api(page, "/home-assistant/connection", "DELETE").catch(() => {});
    await app.close();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
