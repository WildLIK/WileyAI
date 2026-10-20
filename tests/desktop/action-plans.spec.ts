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
async function say(page: Page, text: string, answer: string) {
  await page.getByLabel("Сообщение", { exact: true }).fill(text);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(
    page.locator(".message.assistant .message-text").last(),
  ).toContainText(answer);
}

test("local plans: mixed review, restart, clarification, saved results and off switch", async () => {
  let requests = 0;
  const model = createServer(async (request, response) => {
    response.setHeader("Content-Type", "application/json");
    if (request.method === "GET") {
      response.end(JSON.stringify({ data: [{ id: "plan-fixture" }] }));
      return;
    }
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    const text = body.messages.at(-1).content as string;
    requests++;
    expect(body.response_format).toBeTruthy();
    const tomorrow = new Date(Date.now() + 86400000).toLocaleDateString(
      "sv-SE",
      { timeZone: "Asia/Yekaterinburg" },
    );
    const content = text.includes("Обзор")
      ? {
          steps: [
            {
              domain: "event",
              action: "create",
              source: text,
              title: "Обзор",
              day: tomorrow,
              clock: "",
            },
          ],
        }
      : {
          steps: [
            {
              domain: "task",
              action: "create",
              source: "Напомни завтра в 10 оплатить интернет",
              title: "оплатить интернет",
              kind: "reminder",
              day: tomorrow,
              clock: "10:00",
              repeat: "none",
            },
            {
              domain: "note",
              action: "create",
              source: "запиши заметку Документы: забрать паспорт",
              title: "Документы",
              content: "забрать паспорт",
            },
          ],
        };
    response.setHeader("Content-Type", "text/event-stream");
    response.end(
      "data: " +
        JSON.stringify({
          choices: [
            {
              delta: { content: JSON.stringify(content) },
              finish_reason: "stop",
            },
          ],
        }) +
        "\n\ndata: [DONE]\n\n",
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string")
    throw new Error("Missing model port");
  const data = await mkdtemp(join(tmpdir(), "wiley-mixed-plans-"));
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
    await api(page, "/settings", "PUT", {
      ...(await api(page, "/settings")),
      provider: "compatible",
      base_url: `http://127.0.0.1:${address.port}/v1`,
      model: "plan-fixture",
      plan_understanding: true,
    });
    await page.reload();
    const phrase =
      "Напомни завтра в 10 оплатить интернет; запиши заметку Документы: забрать паспорт";
    await say(page, phrase, "Выполнить весь план");
    expect(await api(page, "/tasks")).toHaveLength(0);
    expect(await api(page, "/notes")).toHaveLength(0);
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("План действий");
    await say(page, "выполни план", "План выполнен");
    expect(await api(page, "/tasks")).toHaveLength(1);
    expect(await api(page, "/notes")).toHaveLength(1);
    expect(requests).toBe(1);
    await say(
      page,
      "Запланируй встречу Обзор завтра утром",
      "укажите дату и время",
    );
    await say(page, "завтра в 12", "Выполнить весь план");
    await say(page, "да", "План выполнен");
    expect(requests).toBe(2);
    await page.getByRole("button", { name: "⌘ Команды", exact: true }).click();
    const journal = page.getByRole("region", {
      name: "Результаты планов из чата",
      exact: true,
    });
    await expect(journal.locator("details")).toHaveCount(2);
    await journal.locator("summary").first().click();
    await expect(journal).toContainText("результат проверен");
    await mkdir("local/review", { recursive: true });
    await journal.screenshot({ path: "local/review/action-plan-results.png" });
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Личность", exact: true }).click();
    await page
      .getByLabel("Понимать составные просьбы, заметки и календарь", {
        exact: true,
      })
      .uncheck();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    await say(page, phrase, "выключено");
    expect(requests).toBe(2);
    expect(await api(page, "/tasks")).toHaveLength(1);
    expect(await api(page, "/plans/history")).toHaveLength(2);
  } finally {
    await app.close();
    await new Promise<void>((resolve) => model.close(() => resolve()));
  }
});
