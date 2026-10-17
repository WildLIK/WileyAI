import { test, expect, _electron as electron } from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("answer length, visible truncation, explicit continuation and independent persona gender", async () => {
  const prompts: {
    messages: { role: string; content: string }[];
    max_tokens: number;
  }[] = [];
  const partial = "Подробный анализ. ".repeat(400) + "Конец ответа: нужно ли";
  const model = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.end('{"data":[]}');
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    prompts.push(JSON.parse(Buffer.concat(chunks).toString()));
    res.setHeader("Content-Type", "text/event-stream");
    const content = prompts.length === 1 ? partial : "Продолжение без обрыва.";
    res.end(
      "data: " +
        JSON.stringify({ choices: [{ delta: { content } }] }) +
        "\n\ndata: " +
        JSON.stringify({
          choices: [
            {
              delta: {},
              finish_reason: prompts.length === 1 ? "length" : "stop",
            },
          ],
        }) +
        "\n\ndata: [DONE]\n\n",
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string")
    throw new Error("No server port");
  const data = await mkdtemp(join(tmpdir(), "wiley-completion-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await expect(
      page.getByLabel("Род речи персонажа", { exact: true }),
    ).toHaveValue("feminine");
    await expect(
      page.getByLabel("Максимальная длина ответа, токенов", { exact: true }),
    ).toHaveValue("2048");
    await page.getByLabel("Движок", { exact: true }).selectOption("compatible");
    await page
      .getByLabel("Адрес сервера", { exact: true })
      .fill(`http://127.0.0.1:${address.port}`);
    await page
      .getByLabel("Идентификатор модели", { exact: true })
      .fill("completion-test");
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Настройки сохранены");
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Подробно опиши сюжет");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".message.assistant .message-text")).toHaveText(
      partial,
    );
    await expect(
      page.getByRole("status").filter({ hasText: "достиг лимита" }),
    ).toBeVisible();
    expect(prompts).toHaveLength(1);
    expect(prompts[0].max_tokens).toBe(2048);
    expect(prompts[0].messages[0].content).toContain("женском роде");
    await page
      .getByRole("button", { name: "Продолжить ответ", exact: true })
      .click();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toHaveText("Продолжение без обрыва.");
    expect(prompts).toHaveLength(2);
    expect(JSON.stringify(prompts[1])).toContain("Конец ответа: нужно ли");
    expect(JSON.stringify(prompts[1])).toContain("Подробно опиши сюжет");
    await expect(
      page.getByText("Ответ достиг лимита длины.", { exact: false }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByLabel("Род речи персонажа", { exact: true })
      .selectOption("masculine");
    await page
      .getByLabel("Максимальная длина ответа, токенов", { exact: true })
      .fill("1024");
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Настройки сохранены");
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(page.locator(".message.assistant")).toHaveCount(2);
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await expect(
      page.getByLabel("Род речи персонажа", { exact: true }),
    ).toHaveValue("masculine");
    await expect(
      page.getByLabel("Максимальная длина ответа, токенов", { exact: true }),
    ).toHaveValue("1024");
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    await page
      .getByRole("button", { name: "Продолжить ответ", exact: true })
      .click();
    await expect.poll(() => prompts.length).toBe(3);
    expect(prompts[2].max_tokens).toBe(1024);
    expect(prompts[2].messages[0].content).toContain("мужском роде");
    await expect(page.getByRole("alert")).toBeHidden();
  } finally {
    await app.close();
    await new Promise<void>((resolve) => model.close(() => resolve()));
  }
});
