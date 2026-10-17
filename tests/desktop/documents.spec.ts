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

test("DOCX uploaded from chat stays attached across chat changes and restart and reaches the model", async () => {
  const prompts: { messages: { role: string; content: string }[] }[] = [];
  const model = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.end('{"data":[]}');
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    if (body.messages[0].content.startsWith("Выбери способ чтения")) {
      res.setHeader("Content-Type", "text/event-stream");
      res.end(
        'data: {"choices":[{"delta":{"content":"{\\"mode\\":\\"fragments\\"}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
      );
      return;
    }
    prompts.push(body);
    res.setHeader("Content-Type", "text/event-stream");
    res.end(
      'data: {"choices":[{"delta":{"content":"Код в файле — 7351."}}]}\n\ndata: [DONE]\n\n',
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string") throw new Error("No port");
  const data = await mkdtemp(join(tmpdir(), "wiley-docx-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(async (base_url) => {
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
          base_url,
          model: "docx-test",
        }),
      });
      const channel = new BroadcastChannel("wiley-ui");
      channel.postMessage({ type: "settings" });
      channel.close();
    }, `http://127.0.0.1:${address.port}`);
    await page
      .locator('input[type="file"][accept=".txt,.md,.csv,.pdf,.docx"]')
      .setInputFiles("tests/fixtures/voice-document.docx");
    await expect(page.locator(".doc-chip")).toHaveCount(1);
    await expect(page.locator(".doc-chip")).toContainText("символов текста");
    await page
      .getByRole("button", { name: "＋ Новый чат", exact: true })
      .click();
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeEnabled();
    await expect(page.locator(".doc-chip")).toHaveCount(0);
    await page.locator('.chat-select:not([aria-current="page"])').click();
    await expect(page.locator(".doc-chip")).toHaveCount(1);
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    await expect(page.locator(".doc-chip")).toHaveCount(1);
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Что написано в приложенном документе?");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".message.assistant")).toContainText("7351");
    expect(prompts).toHaveLength(1);
    expect(prompts[0].messages[0].content).toContain("код поставки 7351");
    expect(prompts[0].messages.at(-1)!.content).toContain(
      "voice-document.docx",
    );
    const sources = page.locator(".message.assistant .document-context");
    await expect(sources).toHaveCount(1);
    await expect(sources.locator("blockquote")).not.toBeVisible();
    await sources.locator("summary").click();
    await expect(sources.locator("strong")).toHaveText("voice-document.docx");
    await expect(sources.locator("blockquote")).toContainText(
      "код поставки 7351",
    );
    const excerpt = await sources.locator("blockquote").innerText();
    expect(prompts[0].messages[0].content).toContain(excerpt);
    await expect(sources.locator("small")).toHaveText(/Символы 1–\d+ из \d+/);
    await sources.screenshot({
      path: "local/screenshots/document-context-docx.png",
    });
    // Deleting the file cannot rewrite the historical excerpt used for this answer.
    await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      const headers = { Authorization: "Bearer " + token };
      const chats = await (
        await fetch(url + "/conversations", { headers })
      ).json();
      for (const chat of chats) {
        const docs = await (
          await fetch(url + "/documents?conversation_id=" + chat.id, {
            headers,
          })
        ).json();
        for (const doc of docs)
          await fetch(
            url + "/documents/" + doc.id + "?conversation_id=" + chat.id,
            { method: "DELETE", headers },
          );
      }
    });
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    const restoredSources = page.locator(
      ".message.assistant .document-context",
    );
    await restoredSources.locator("summary").click();
    await expect(restoredSources.locator("blockquote")).toHaveText(excerpt);
    await expect(page.locator(".doc-chip")).toHaveCount(0);
    await expect(page.getByRole("alert")).toBeHidden();
  } finally {
    await app.close();
    await new Promise<void>((resolve) => model.close(() => resolve()));
  }
});

test("documents: local search, preview, explicit project copy, model selection, window updates and restart", async () => {
  const prompts: { messages: { role: string; content: string }[] }[] = [];
  const model = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ data: [{ id: "document-test" }] }));
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    if (body.messages[0].content.startsWith("Выбери способ чтения")) {
      res.setHeader("Content-Type", "text/event-stream");
      res.end(
        'data: {"choices":[{"delta":{"content":"{\\"mode\\":\\"fragments\\"}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
      );
      return;
    }
    prompts.push(body);
    res.setHeader("Content-Type", "text/event-stream");
    res.end(
      'data: {"choices":[{"delta":{"content":"Ответ по выбранным данным."}}]}\n\ndata: [DONE]\n\n',
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string") throw new Error("No model port");
  const data = await mkdtemp(join(tmpdir(), "wileyai-documents-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  const docs = (page: Page) =>
    page.getByRole("button", { name: "▧ Документы", exact: true }).click();
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
      const { url, token } = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      };
      const config = await (await fetch(url + "/settings", { headers })).json();
      await fetch(url + "/settings", {
        headers,
        method: "PUT",
        body: JSON.stringify({
          ...config,
          provider: "compatible",
          base_url,
          model: "document-test",
        }),
      });
      const channel = new BroadcastChannel("wiley-ui");
      channel.postMessage({ type: "settings" });
      channel.close();
    }, `http://127.0.0.1:${address.port}`);
    await page.getByRole("button", { name: "＋ Проект", exact: true }).click();
    await page.getByLabel("Название проекта").fill("Документы проекта");
    await page
      .getByRole("button", { name: "Создать проект", exact: true })
      .click();
    await expect(page.locator(".chat-toolbar small")).toContainText(
      "Документы проекта",
    );
    await docs(page);
    await page.getByLabel("Добавить файл", { exact: true }).setInputFiles({
      name: "План.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "НАЧАЛО\n" + "пусто ".repeat(2400) + "\nФЕНИКС: КОНТРОЛЬНЫЙ КОД 7351",
        "utf-8",
      ),
    });
    await page
      .getByRole("button", { name: "Загрузить документ", exact: true })
      .click();
    await expect(page.locator(".document-entry")).toHaveCount(1);
    await expect(page.locator(".document-entry")).toContainText(
      "Только этот чат",
    );
    await page.getByLabel("Найти в документах").fill("феникс");
    await page.getByRole("button", { name: "Найти", exact: true }).click();
    await expect(page.locator(".document-excerpt")).toContainText("7351");
    await page
      .getByRole("button", { name: "Просмотреть текст", exact: true })
      .click();
    await expect(page.locator(".document-preview pre")).toContainText("НАЧАЛО");
    await expect(page.locator(".document-preview pre")).not.toContainText(
      "7351",
    );
    await page
      .getByRole("button", { name: "Следующий фрагмент", exact: true })
      .click();
    await expect(page.locator(".document-preview pre")).toContainText("7351");
    await page
      .getByRole("button", { name: "Закрыть просмотр", exact: true })
      .click();
    await page
      .getByRole("checkbox", {
        name: "Выбрать «План.txt» для вопроса",
        exact: true,
      })
      .check();
    expect(prompts).toHaveLength(0);
    await page
      .getByRole("button", { name: "Создать копию для проекта", exact: true })
      .click();
    await expect(page.locator(".document-entry")).toHaveCount(2);
    await page
      .getByRole("button", {
        name: "Новый чат в проекте «Документы проекта»",
        exact: true,
      })
      .click();
    await expect(page.locator(".chat-toolbar h1")).toHaveText("Новый чат");
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeEnabled();
    await docs(page);
    await expect(page.locator(".document-entry")).toHaveCount(1);
    await expect(page.locator(".document-entry")).toContainText(
      "Документ проекта",
    );
    await expect(
      page.getByRole("checkbox", {
        name: "Выбрать «План.txt» для вопроса",
        exact: true,
      }),
    ).not.toBeChecked();
    await page
      .getByRole("checkbox", {
        name: "Выбрать «План.txt» для вопроса",
        exact: true,
      })
      .check();
    await page
      .getByRole("button", { name: "К вопросу · 1/10", exact: true })
      .click();
    await expect(page.locator(".doc-chip")).toHaveCount(1);
    await send(page, "Какой контрольный код ФЕНИКС в файле?");
    expect(prompts.at(-1)!.messages[0].content).toContain("7351");
    await expect(page.locator(".document-context")).toHaveCount(1);
    await page
      .getByRole("button", { name: "Убрать из вопроса План.txt", exact: true })
      .click();
    await expect(page.locator(".doc-chip")).toHaveCount(0);
    await send(page, "Поговорим о погоде");
    expect(prompts.at(-1)!.messages[0].content).not.toContain("7351");
    await expect(
      page.locator(".message.assistant").last().locator(".document-context"),
    ).toHaveCount(0);
    await docs(page);
    await expect(page.locator(".document-entry")).toHaveCount(1);
    await page
      .getByRole("checkbox", {
        name: "Выбрать «План.txt» для вопроса",
        exact: true,
      })
      .check();
    await page
      .getByRole("button", { name: "К вопросу · 1/10", exact: true })
      .click();
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await docs(second);
    await expect(second.locator(".document-entry")).toHaveCount(1);
    await page.route(
      "**/chat",
      (route) =>
        route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Выбранный документ удалён. Выберите документы заново",
          }),
        }),
      { times: 1 },
    );
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Сохрани этот вопрос при ошибке выбора файла");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText(
      "Выбранный документ удалён",
    );
    await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue(
      "Сохрани этот вопрос при ошибке выбора файла",
    );
    expect(prompts).toHaveLength(2);
    await page
      .getByRole("button", { name: "Закрыть ошибку", exact: true })
      .click();
    await second
      .getByRole("button", { name: "Удалить из проекта", exact: true })
      .click();
    await expect(second.locator(".document-entry")).toHaveCount(0);
    await expect(page.locator(".doc-chip")).toHaveCount(0);
    const group = page
      .locator(".project-group")
      .filter({ hasText: "Документы проекта" });
    await group
      .locator(".chat-select")
      .filter({ hasText: "Новый чат" })
      .click();
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeEnabled();
    await docs(page);
    await expect(page.locator(".document-entry")).toHaveCount(1);
    await page
      .getByRole("button", { name: "Создать копию для проекта", exact: true })
      .click();
    await expect(page.locator(".document-entry")).toHaveCount(2);
    // A delayed response to an earlier search cannot replace the current results.
    let unblock!: () => void, entered!: () => void;
    const gate = new Promise<void>((resolve) => {
      unblock = resolve;
    });
    const blocked = new Promise<void>((resolve) => {
      entered = resolve;
    });
    await page.route("**/documents/library?**", async (route) => {
      if (new URL(route.request().url()).searchParams.get("q") === "задержка") {
        entered();
        await gate;
      }
      await route.continue();
    });
    await page.getByLabel("Найти в документах").fill("задержка");
    await page.getByRole("button", { name: "Найти", exact: true }).click();
    await blocked;
    await page.getByLabel("Найти в документах").fill("феникс");
    await page.getByRole("button", { name: "Найти", exact: true }).click();
    await expect(page.locator(".document-entry")).toHaveCount(2);
    unblock();
    await page.unrouteAll({ behavior: "wait" });
    await expect(page.locator(".document-entry")).toHaveCount(2);
    await page.screenshot({
      path: "local/screenshots/documents.png",
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "＋ Новый чат", exact: true })
      .click();
    await expect(page.locator(".chat-toolbar h1")).toHaveText("Новый чат");
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeEnabled();
    await docs(page);
    await expect(page.locator(".document-entry")).toHaveCount(0);
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
    await docs(page);
    await expect(page.locator(".document-entry")).toHaveCount(0);
    const group = page
      .locator(".project-group")
      .filter({ hasText: "Документы проекта" });
    await group
      .locator(".chat-select")
      .filter({ hasText: "Новый чат" })
      .click();
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeEnabled();
    await docs(page);
    await expect(page.locator(".document-entry")).toHaveCount(2);
    await page.getByLabel("Найти в документах").fill("феникс");
    await page.getByRole("button", { name: "Найти", exact: true }).click();
    await expect(page.locator(".document-excerpt").first()).toContainText(
      "7351",
    );
  } finally {
    await app.close();
    await new Promise<void>((resolve) => model.close(() => resolve()));
  }
});
