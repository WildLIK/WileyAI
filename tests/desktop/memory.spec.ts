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

test("memory: review, source, replacement, context, forgetting, cross-window updates and persistence", async () => {
  // Only the model transport is replaced; extraction, SQLite, API and UI are real.
  const prompts: { messages: { role: string; content: string }[] }[] = [];
  const model = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ data: [{ id: "memory-test" }] }));
      return;
    }
    const parts = [];
    for await (const part of req) parts.push(part);
    prompts.push(JSON.parse(Buffer.concat(parts).toString()));
    res.setHeader("Content-Type", "text/event-stream");
    res.end(
      'data: {"choices":[{"delta":{"content":"Давай обсудим."}}]}\n\ndata: [DONE]\n\n',
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string") throw new Error("No model port");
  const data = await mkdtemp(join(tmpdir(), "wileyai-memory-"));
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
    const chat = await app.firstWindow();
    const errors: string[] = [];
    chat.on("pageerror", (error) => errors.push(error.message));
    await expect(
      chat.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await chat.evaluate(async (base_url) => {
      const connection = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + connection.token,
        "Content-Type": "application/json",
      };
      const config = await (
        await fetch(connection.url + "/settings", { headers })
      ).json();
      const result = await fetch(connection.url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...config,
          provider: "compatible",
          base_url,
          model: "memory-test",
        }),
      });
      if (!result.ok) throw new Error("Settings rejected");
      const channel = new BroadcastChannel("wiley-ui");
      channel.postMessage({ type: "settings" });
      channel.close();
    }, `http://127.0.0.1:${address.port}`);
    const opened = app.waitForEvent("window");
    await chat.evaluate(() => window.wiley.showWindow("settings"));
    const memory = await opened;
    await memory.getByRole("button", { name: "◎ Память" }).click();
    await send(chat, "Я предпочитаю короткие ответы");
    await expect(chat.locator(".memory-suggestion")).toHaveCount(1);
    await expect(memory.locator(".memory-suggestion")).toHaveCount(1);
    await expect(memory.locator(".memory-entry")).toHaveCount(0);
    expect(prompts[0].messages[0].content).toContain("\n[]");
    await chat.getByText("Исходная реплика", { exact: true }).click();
    await expect(chat.locator(".memory-suggestion blockquote")).toHaveText(
      "Я предпочитаю короткие ответы",
    );
    await chat
      .getByLabel("Текст предложения памяти")
      .fill("Я предпочитаю короткие ответы с примерами");
    await chat.getByRole("button", { name: "Принять в память" }).click();
    await expect(memory.locator(".memory-entry")).toHaveCount(1);
    await expect(memory.locator(".memory-entry .memory-content")).toHaveText(
      "Я предпочитаю короткие ответы с примерами",
    );
    await expect(chat.locator(".memory-suggestion")).toHaveCount(0);
    await send(chat, "Как мне объяснять задачи?");
    expect(prompts.at(-1)!.messages[0].content).toContain(
      "короткие ответы с примерами",
    );
    await chat.locator(".memory-context summary").last().click();
    await expect(chat.locator(".memory-context li")).toHaveText(
      "Я предпочитаю короткие ответы с примерами",
    );
    await memory
      .getByRole("button", { name: "Закрепить", exact: true })
      .click();
    await expect(memory.locator(".memory-entry")).toContainText("Закреплено");
    // Pinning must not erase the explanation of an earlier answer.
    await expect(chat.locator(".memory-context")).toHaveCount(1);
    await memory.getByRole("button", { name: "Изменить", exact: true }).click();
    await memory
      .getByLabel("Текст записи памяти")
      .fill("Я предпочитаю короткие ответы с кодом");
    await memory.getByRole("button", { name: "Сохранить запись" }).click();
    await expect(chat.locator(".memory-context")).toHaveCount(0);
    await memory.getByLabel("Поиск по памяти").fill("кодом");
    await expect(memory.locator(".memory-entry")).toHaveCount(1);
    await memory.getByLabel("Поиск по памяти").fill("несуществующее");
    await expect(memory.locator(".memory-entry")).toHaveCount(0);
    await memory.getByLabel("Поиск по памяти").fill("");
    await send(chat, "Я предпочитаю подробные ответы");
    await expect(chat.locator(".memory-suggestion")).toHaveCount(1);
    await chat
      .getByLabel("Заменить запись памяти")
      .selectOption({
        label: "Заменить: Я предпочитаю короткие ответы с кодом",
      });
    await chat.getByRole("button", { name: "Принять и заменить" }).click();
    await expect(memory.locator(".memory-entry")).toHaveCount(1);
    await expect(memory.locator(".memory-entry")).toContainText(
      "подробные ответы",
    );
    await expect(memory.locator(".memory-entry")).toContainText("Закреплено");
    await send(chat, "Какие предпочтения у меня сохранены?");
    expect(prompts.at(-1)!.messages[0].content).toContain("подробные ответы");
    expect(prompts.at(-1)!.messages[0].content).not.toContain(
      "короткие ответы с кодом",
    );
    await expect(chat.locator(".memory-context")).toHaveCount(1);
    await memory
      .getByRole("button", {
        name: "Удалить запись Я предпочитаю подробные ответы",
      })
      .click();
    await expect(chat.locator(".memory-context")).toHaveCount(0);
    await send(chat, "Мне удобнее примеры на Python");
    await expect(chat.locator(".memory-suggestion")).toHaveCount(1);
    await chat.getByRole("button", { name: "Отклонить", exact: true }).click();
    await expect(chat.locator(".memory-suggestion")).toHaveCount(0);
    await send(chat, "Мне удобнее примеры на Python");
    await expect(chat.locator(".memory-suggestion")).toHaveCount(0);
    await send(chat, "Мой проект называется Альтаир");
    await expect(chat.locator(".memory-suggestion")).toHaveCount(1);
    await chat.screenshot({
      path: "local/screenshots/memory-chat.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    // Allow shutdown to close the model's keepalive connections.
    model.closeAllConnections();
    await new Promise<void>((resolve) => model.close(() => resolve()));
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await page.getByRole("button", { name: "◎ Память" }).click();
    await expect(page.locator(".memory-entry")).toHaveCount(0);
    await expect(page.locator(".memory-suggestion")).toHaveCount(1);
    await expect(page.getByLabel("Текст предложения памяти")).toHaveValue(
      "Мой проект называется Альтаир",
    );
    await page.getByRole("button", { name: "Принять в память" }).click();
    await expect(page.locator(".memory-entry .memory-content")).toHaveText(
      "Мой проект называется Альтаир",
    );
    await page.screenshot({
      path: "local/screenshots/memory.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
});
