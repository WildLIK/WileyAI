import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp, writeFile, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("free commands: opt-in, catalog-only model request, durable proposal, local reply, stale path and cancellation", async () => {
  const requests: { messages: { role: string; content: string }[] }[] = [];
  const model = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ data: [{ id: "intent-test" }] }));
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    requests.push(body);
    const catalog = JSON.parse(body.messages[0].content.split("Каталог:\n")[1]);
    const choice = catalog.find(
      (item: { name: string }) => item.name === "редактор заметок",
    );
    res.setHeader("Content-Type", "text/event-stream");
    res.end(
      "data: " +
        JSON.stringify({
          choices: [
            { delta: { content: JSON.stringify({ candidates: [choice.id] }) } },
          ],
        }) +
        "\n\ndata: [DONE]\n\n",
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string") throw new Error("No model port");
  const data = await mkdtemp(join(tmpdir(), "wileyai-intents-"));
  const target = join(data, "private-local-notes.exe");
  await writeFile(target, "test placeholder, never executed");
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  const send = async (page: Page, text: string, expected: string) => {
    await page.getByLabel("Сообщение", { exact: true }).fill(text);
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText(expected);
    await expect(
      page.getByRole("button", { name: "Отправить", exact: true }),
    ).toBeVisible();
  };
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(
      async ({ base_url, target }) => {
        const { url, token } = await window.wiley.connection();
        const headers = {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        };
        const settings = await (
          await fetch(url + "/settings", { headers })
        ).json();
        await fetch(url + "/settings", {
          headers,
          method: "PUT",
          body: JSON.stringify({
            ...settings,
            provider: "compatible",
            base_url,
            model: "intent-test",
          }),
        });
        await fetch(url + "/aliases", {
          headers,
          method: "POST",
          body: JSON.stringify({
            name: "редактор заметок",
            kind: "app",
            target,
          }),
        });
      },
      { base_url: `http://127.0.0.1:${address.port}`, target },
    );
    await page.reload();
    await page.getByRole("button", { name: "⌘ Команды" }).click();
    const understanding = page.getByLabel(
      "Понимать свободные команды с помощью модели",
      { exact: true },
    );
    await expect(understanding).not.toBeChecked();
    await understanding.check();
    await page
      .getByRole("button", { name: "Сохранить доступ", exact: true })
      .click();
    await expect(
      page.getByText("Доступ сохранён", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "◈ Общение" }).click();
    await send(page, "Запомни: ПРИВАТНАЯ-ПАМЯТЬ", "Запомнил");
    await send(
      page,
      "Можешь открыть программу для личных заметок?",
      "Пока ничего не открывал",
    );
    expect(requests).toHaveLength(1);
    expect(requests[0].messages).toHaveLength(2);
    expect(JSON.stringify(requests[0])).not.toContain("ПРИВАТНАЯ-ПАМЯТЬ");
    expect(JSON.stringify(requests[0])).not.toContain(target);
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText(target);
    await page.screenshot({
      path: "local/screenshots/intents.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
  try {
    app = await launch();
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("Пока ничего не открывал");
    // Remove the placeholder before confirming: actual preflight must refuse it.
    await unlink(target);
    await send(page, "да", "Файл или папка не найдены");
    expect(requests).toHaveLength(1);
    await writeFile(target, "test placeholder, never executed");
    await send(
      page,
      "Открой программу для личных заметок",
      "Пока ничего не открывал",
    );
    await send(page, "отмена", "Выбор открытия отменён");
    expect(requests).toHaveLength(2);
    await page.getByRole("button", { name: "⌘ Команды" }).click();
    await expect(
      page.getByLabel("Понимать свободные команды с помощью модели", {
        exact: true,
      }),
    ).toBeChecked();
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    model.closeAllConnections();
    await new Promise<void>((resolve) => model.close(() => resolve()));
  }
});
