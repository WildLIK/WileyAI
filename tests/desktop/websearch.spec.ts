import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { createServer, type ServerResponse } from "node:http";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("web search: explicit opt-in, real provider HTTP, citations, one-shot button, cancellation and persistence", async () => {
  const searches: URL[] = [];
  let delayed: ServerResponse | undefined;
  const server = createServer(async (req, res) => {
    const url = new URL(req.url || "/", "http://127.0.0.1");
    if (url.pathname === "/search") {
      searches.push(url);
      if (url.searchParams.get("q") === "медленный поиск") {
        delayed = res;
        return;
      }
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify({
          results: [
            {
              title: "<b>Первый источник</b>",
              url: "https://example.com/releases",
              content: "Контрольный код КЕДР-84.",
            },
            {
              title: "Ещё источник",
              url: "https://example.org/news",
              content: "Дата выпуска не назначена.",
            },
            {
              title: "Нельзя открывать",
              url: "javascript:alert(1)",
              content: "ignored",
            },
          ],
        }),
      );
      return;
    }
    if (req.method === "GET") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ data: [{ id: "search-test-model" }] }));
      return;
    }
    const body = [];
    for await (const part of req) body.push(part);
    const payload = JSON.parse(Buffer.concat(body).toString());
    const searched = payload.messages[0].content.includes("КЕДР-84");
    res.setHeader("Content-Type", "text/event-stream");
    res.end(
      "data: " +
        JSON.stringify({
          choices: [
            {
              delta: {
                content: searched
                  ? "Код выпуска КЕДР-84 [1]. Даты пока нет [2]."
                  : "Обычный ответ.",
              },
            },
          ],
        }) +
        "\n\ndata: [DONE]\n\n",
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("No server port");
  const base_url = `http://127.0.0.1:${address.port}`;
  const data = await mkdtemp(join(tmpdir(), "wileyai-websearch-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  const send = async (page: Page, text: string) => {
    const count = await page.locator(".message.assistant").count();
    await page.getByLabel("Сообщение", { exact: true }).fill(text);
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".message.assistant")).toHaveCount(count + 1);
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
    await page.evaluate(async (base_url) => {
      const connection = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + connection.token,
        "Content-Type": "application/json",
      };
      const config = await (
        await fetch(connection.url + "/settings", { headers })
      ).json();
      await fetch(connection.url + "/settings", {
        headers,
        method: "PUT",
        body: JSON.stringify({
          ...config,
          provider: "compatible",
          base_url,
          model: "search-test-model",
        }),
      });
      const channel = new BroadcastChannel("wiley-ui");
      channel.postMessage({ type: "settings" });
      channel.close();
    }, base_url);
    await page
      .getByRole("button", {
        name: "Поиск в интернете для следующего сообщения",
      })
      .click();
    await expect(
      page.getByRole("heading", { name: "Настройки ассистента" }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Разрешить веб-поиск по моей команде"),
    ).not.toBeChecked();
    expect(searches).toHaveLength(0);
    await page.getByLabel("Адрес SearXNG").fill(base_url);
    await page.getByLabel("Фильтр результатов").selectOption("strict");
    await page.getByLabel("Разрешить веб-поиск по моей команде").check();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Настройки сохранены");
    await expect(page.locator(".connection")).toHaveText("search-test-model");
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await second.getByRole("button", { name: "◈ Общение" }).click();
    await page.getByRole("button", { name: "◈ Общение" }).click();
    await send(page, "Найди в интернете код выпуска WileyAI");
    await expect(page.locator(".search-sources li")).toHaveCount(2);
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("КЕДР-84 [1]");
    await expect(second.locator(".search-sources li")).toHaveCount(2);
    await page.locator(".search-sources").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: "local/screenshots/websearch-sources.png",
      fullPage: true,
    });
    expect(searches[0].searchParams.get("q")).toBe("код выпуска WileyAI");
    expect(searches[0].searchParams.get("safesearch")).toBe("2");
    await expect(
      page.getByRole("button", {
        name: "Открыть источник 1: Первый источник",
        exact: true,
      }),
    ).toBeVisible();
    const openedSources: unknown[] = [];
    await page.route("**/web/open-source*", (route) => {
      openedSources.push(route.request().postDataJSON());
      return route.fulfill({ json: { text: "Передал браузеру источник" } });
    });
    await page
      .getByRole("button", {
        name: "Открыть источник 1: Первый источник",
        exact: true,
      })
      .click();
    await expect(page.getByRole("status")).toHaveText(
      "Передал браузеру источник",
    );
    expect(openedSources).toEqual([
      { message_id: expect.any(String), index: 0 },
    ]);
    await page
      .getByRole("button", {
        name: "Поиск в интернете для следующего сообщения",
      })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Поиск в интернете для следующего сообщения",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    await send(page, "какие обновления появились?");
    expect(searches).toHaveLength(2);
    await expect(
      page.getByRole("button", {
        name: "Поиск в интернете для следующего сообщения",
      }),
    ).toHaveAttribute("aria-pressed", "false");
    await send(page, "Давай поговорим о звёздах");
    expect(searches).toHaveLength(2);
    await second.getByRole("button", { name: "⚙ Настройки" }).click();
    await second.getByRole("tab", { name: "Поиск", exact: true }).click();
    await second.getByLabel("Разрешить веб-поиск по моей команде").uncheck();
    await second
      .getByRole("button", { name: "Сохранить", exact: true })
      .click();
    await expect(second.getByRole("status")).toHaveText("Настройки сохранены");
    await send(page, "Найди в интернете новости WileyAI");
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("Поиск в интернете выключен");
    expect(searches).toHaveLength(2);
    await second.getByLabel("Разрешить веб-поиск по моей команде").check();
    await second
      .getByRole("button", { name: "Сохранить", exact: true })
      .click();
    await expect(second.getByRole("status")).toHaveText("Настройки сохранены");
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Найди в интернете медленный поиск");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".thinking")).toHaveText("Ищу в интернете…");
    await expect.poll(() => Boolean(delayed)).toBe(true);
    await page
      .getByRole("button", { name: "Остановить ответ", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Отправить", exact: true }),
    ).toBeVisible({ timeout: 10000 });
    delayed!.end(JSON.stringify({ results: [] }));
    await send(page, "Запомни: отмена поиска работает");
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("Запомнила");
    await expect(page.locator(".search-sources")).toHaveCount(2);
    await page.screenshot({
      path: "local/screenshots/websearch.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
  try {
    app = await launch();
    const page = await app.firstWindow();
    await expect(page.locator(".search-sources")).toHaveCount(2);
    await page.getByRole("button", { name: "⚙ Настройки" }).click();
    await expect(
      page.getByLabel("Разрешить веб-поиск по моей команде"),
    ).toBeChecked();
    await expect(page.getByLabel("Адрес SearXNG")).toHaveValue(base_url);
    await expect(page.getByLabel("Фильтр результатов")).toHaveValue("strict");
    expect(searches).toHaveLength(3);
  } finally {
    await app.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
