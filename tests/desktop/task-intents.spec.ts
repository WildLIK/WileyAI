import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function send(page: Page, text: string, expected: string) {
  await page.getByLabel("Сообщение", { exact: true }).fill(text);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(
    page.locator(".message.assistant .message-text").last(),
  ).toContainText(expected);
}

async function records(page: Page) {
  return page.evaluate(async () => {
    const { url, token } = await window.wiley.connection();
    return (
      await fetch(url + "/tasks", {
        headers: { Authorization: "Bearer " + token },
      })
    ).json();
  });
}

test("natural tasks: structured preview, restart, one confirmation and a persistent off switch", async () => {
  let structured = 0;
  const day = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  const model = createServer(async (request, response) => {
    if (request.method === "GET") {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({ data: [{ id: "task-fixture" }] }));
      return;
    }
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    let content = "Задачи не изменены.";
    if (body.response_format) {
      structured++;
      content = JSON.stringify({
        action: "create",
        kind: "reminder",
        title: "оплатить интернет",
        candidates: [],
        day,
        clock: "12:00",
        seconds: null,
        repeat: "none",
        weekdays: [],
        reason: "",
      });
    }
    response.setHeader("Content-Type", "text/event-stream");
    response.end(
      "data: " +
        JSON.stringify({
          choices: [{ delta: { content }, finish_reason: "stop" }],
        }) +
        "\n\ndata: [DONE]\n\n",
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string")
    throw new Error("Missing model port");
  const data = await mkdtemp(join(tmpdir(), "wiley-task-plans-"));
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
    await page.evaluate(async (port) => {
      const { url, token } = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      };
      const config = await (await fetch(url + "/settings", { headers })).json();
      await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...config,
          provider: "compatible",
          base_url: `http://127.0.0.1:${port}/v1`,
          model: "task-fixture",
          task_understanding: true,
        }),
      });
    }, address.port);
    await page.reload();
    await send(
      page,
      "Не забудь напомнить мне завтра к полудню оплатить интернет",
      "Выполнить?",
    );
    expect(await records(page)).toEqual([]);
    expect(structured).toBe(1);
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("План задачи:");
    await send(page, "да", "Создана запись");
    const tasks = await records(page);
    expect(tasks).toHaveLength(1);
    expect(tasks[0].title).toBe("оплатить интернет");
    expect(structured).toBe(1);
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Личность", exact: true }).click();
    await page.getByLabel("Понимать свободные просьбы о задачах").uncheck();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    await send(
      page,
      "Не забудь напомнить мне завтра позвонить",
      "Задачи не изменены",
    );
    expect(structured).toBe(1);
    await send(page, "Создай задачу купить хлеб", "создана");
    expect(await records(page)).toHaveLength(2);
    await page.screenshot({
      path: "local/screenshots/task-plans.png",
      animations: "disabled",
    });
  } finally {
    await app.close();
    await new Promise<void>((resolve, reject) =>
      model.close((error) => (error ? reject(error) : resolve())),
    );
  }
});
