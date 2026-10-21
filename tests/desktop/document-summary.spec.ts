import { test, expect, _electron as electron } from "@playwright/test";
import { createServer, type ServerResponse } from "node:http";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("whole-file reading: animated progress, cancellation, all chunks and final ending persist", async () => {
  let hold = true;
  let pending: ServerResponse | undefined;
  let stopped = false;
  let continueReading: (() => void) | undefined;
  const reads: string[] = [];
  const prompts: { role: string; content: string }[][] = [];
  const server = createServer(async (req, res) => {
    if (req.method !== "POST") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ data: [{ id: "summary-test" }] }));
      return;
    }
    let body = "";
    for await (const chunk of req) body += chunk;
    const { messages, response_format } = JSON.parse(body);
    prompts.push(messages);
    const reading = messages[0].content.startsWith("Выбери опорные отрывки");
    const merging = messages[0].content.startsWith("Отбери ключевые отрывки");
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    if (reading && hold) {
      pending = res;
      res.on("close", () => {
        stopped = true;
      });
      res.flushHeaders();
      return;
    }
    if (reading)
      reads.push(
        JSON.parse(messages[1].content)
          .map((row: { text: string }) => row.text)
          .join(""),
      );
    if (reading && reads.length === 2)
      await new Promise<void>((done) => {
        continueReading = done;
      });
    let text: string;
    if (messages[0].content.startsWith("Выбери способ чтения")) {
      text =
        "Я готова прочитать документ. Выберите режим: " +
        JSON.stringify({
          mode: messages.at(-1).content.includes("прочитай")
            ? "full"
            : "fragments",
        });
    } else if (reading || merging) {
      const rows = JSON.parse(messages[1].content) as { id: number }[];
      text = JSON.stringify({
        ids: reading
          ? [...new Set([rows[0].id, rows.at(-1)!.id])]
          : [rows[0].id],
      });
    } else if (
      messages[0].content.startsWith("Составь краткий хронологический пересказ")
    ) {
      const parts =
        response_format.json_schema.schema.properties.claims.properties;
      text = JSON.stringify({
        claims: Object.fromEntries(
          Object.entries(parts).map(([key, spec]) => {
            const ids = (
              spec as { properties: { sources: { items: { enum: number[] } } } }
            ).properties.sources.items.enum;
            return [
              key,
              {
                text: "Финал: ЗАКАТ-7351, герой вернулся домой.",
                sources: [ids.at(-1)],
              },
            ];
          }),
        ),
      });
    } else if (
      messages[0].content.startsWith("Проверь утверждения пересказа")
    ) {
      text = JSON.stringify({
        supported: JSON.parse(messages[1].content).map(
          (row: { id: number }) => row.id,
        ),
      });
    } else {
      text =
        "Это история расследования кражи. Здесь доступны выбранные отрывки.";
    }
    res.write(
      "data: " +
        JSON.stringify({ choices: [{ delta: { content: text } }] }) +
        "\n\n",
    );
    res.end(
      "data: " +
        JSON.stringify({ choices: [{ delta: {}, finish_reason: "stop" }] }) +
        "\n\ndata: [DONE]\n\n",
    );
  });
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("No test port");
  const data = await mkdtemp(join(tmpdir(), "wiley-document-summary-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const composer = page.getByLabel("Сообщение", { exact: true });
    await expect(composer).toBeVisible();
    await page.evaluate(async (base_url) => {
      const { url, token } = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      };
      const config = await (await fetch(url + "/settings", { headers })).json();
      const response = await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...config,
          provider: "compatible",
          base_url,
          model: "summary-test",
          speak_answers: false,
        }),
      });
      if (!response.ok) throw new Error("Cannot configure fixture model");
    }, `http://127.0.0.1:${address.port}`);
    const content =
      "НАЧАЛО: кража.\n" +
      "Рейдж идёт по городу и ищет пропавший груз.\n".repeat(2500) +
      "КОНЕЦ: ЗАКАТ-7351, герой вернулся домой.";
    await page
      .locator('input[type="file"][accept=".txt,.md,.csv,.pdf,.docx"]')
      .setInputFiles({
        name: "Книга.txt",
        mimeType: "text/plain",
        buffer: Buffer.from(content),
      });
    const whole = page.getByRole("button", {
      name: "Пересказать целиком",
      exact: true,
    });
    await expect(whole).toBeVisible();
    await composer.fill("Про что этот файл?");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".document-coverage")).toContainText(
      "Это не чтение файла целиком",
    );
    expect(
      prompts.some((messages) =>
        messages[0].content.includes("конец отрывка НЕ означает конец файла"),
      ),
    ).toBe(true);
    await expect(whole).toBeEnabled();
    await whole.click();
    await expect.poll(() => !!pending).toBe(true);
    const progress = page.getByRole("progressbar");
    await expect(progress).toBeVisible();
    await expect(progress).not.toHaveAttribute("aria-valuenow");
    expect(
      await progress
        .locator("span")
        .evaluate((el) => getComputedStyle(el).animationName),
    ).toContain("document-progress-flow");
    await page.setViewportSize({ width: 850, height: 650 });
    await progress.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: "local/screenshots/document-reading-progress.png",
    });
    await page
      .getByRole("button", { name: "Остановить чтение документа", exact: true })
      .click();
    await expect(progress).toHaveCount(0);
    await expect.poll(() => stopped).toBe(true);
    await expect(page.locator(".message.assistant")).toHaveCount(1);
    hold = false;
    reads.length = 0;
    await expect(whole).toBeEnabled();
    await composer.fill("прочитай");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect.poll(() => !!continueReading).toBe(true);
    await expect(progress).toHaveAttribute("aria-valuenow", /^[1-9]\d?$/);
    await progress.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: "local/screenshots/document-reading-count.png",
    });
    continueReading!();
    await expect(page.locator(".message.assistant").last()).toContainText(
      "обработан весь извлечённый текст",
      { timeout: 30000 },
    );
    await expect(page.locator(".message.assistant").last()).toContainText(
      "ЗАКАТ-7351",
    );
    await expect(progress).toHaveCount(0);
    expect(reads.length).toBeGreaterThan(10);
    expect(reads.join("")).toBe(content);
    await expect(page.locator(".message.assistant").last()).not.toContainText(
      "wiley_document_action",
    );
    await expect(page.locator(".message.assistant").last()).not.toContainText(
      "Выберите режим",
    );
    expect(
      prompts.some((messages) =>
        messages[0].content.startsWith("Отбери ключевые отрывки"),
      ),
    ).toBe(true);
    await page.reload();
    await expect(page.locator(".message.assistant").last()).toContainText(
      "обработан весь извлечённый текст",
    );
    await expect(page.locator(".message.assistant").last()).toContainText(
      "ЗАКАТ-7351",
    );
    const lastMessage = page.locator(".message.assistant").last();
    await expect(lastMessage.locator(".document-coverage")).toHaveCount(0);
    await lastMessage.getByText(/Опорные фрагменты пересказа/).click();
    await expect(lastMessage.locator("blockquote").last()).toContainText(
      "ЗАКАТ-7351",
    );
    await expect(lastMessage).not.toContainText("не прошёл проверку");
    await lastMessage.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: "local/screenshots/document-summary-grounded.png",
    });
    expect(errors).toEqual([]);
  } finally {
    continueReading?.();
    pending?.destroy();
    await app.close();
    server.closeAllConnections();
    await new Promise<void>((done) => server.close(() => done()));
  }
});
