import { test, expect, _electron as electron } from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("monitor samples idle and a live model request without starting local models", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-monitor-"));
  let finish: (() => void) | undefined;
  const server = createServer((req, res) => {
    if (req.url?.endsWith("/models")) {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ data: [{ id: "monitor-test-model" }] }));
      return;
    }
    if (!req.url?.endsWith("/chat/completions")) {
      res.statusCode = 404;
      res.end();
      return;
    }
    req.resume();
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write(
      'data: {"choices":[{"delta":{"content":"Проверяю нагрузку. "}}]}\n\n',
    );
    finish = () =>
      res.end(
        'data: {"choices":[{"delta":{"content":"Готово."},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
      );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address() as { port: number };
  const app = await electron.launch({
    args: ["."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
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
      const response = await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...config,
          provider: "compatible",
          model: "monitor-test-model",
          base_url,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
    }, `http://127.0.0.1:${address.port}/v1`);
    await page.reload();
    await page.getByRole("button", { name: "▥ Нагрузка", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Нагрузка", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Сейчас модели в простое.", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByRole("row").filter({ hasText: "Ядро и общие модели" }),
    ).toContainText("Простой");
    await expect(page.getByRole("img", { name: /^CPU WileyAI/ })).toBeVisible();
    const idle = await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      return (
        await fetch(url + "/monitor", {
          headers: { Authorization: "Bearer " + token },
        })
      ).json();
    });
    expect(idle.app.ram).toBeGreaterThan(0);
    expect(idle.rows.some((row: { id: string }) => row.id === "desktop")).toBe(
      true,
    );
    expect(
      idle.rows
        .filter((row: { id: string; pids: number[] }) => row.id === "tts:qwen3")
        .flatMap((row: { pids: number[] }) => row.pids),
    ).toEqual([]);
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Расскажи про звёзды");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(
      page.getByText("Проверяю нагрузку.", { exact: false }),
    ).toBeVisible();
    await page.getByRole("button", { name: "▥ Нагрузка", exact: true }).click();
    const model = page
      .getByRole("row")
      .filter({ hasText: "monitor-test-model" });
    await expect(model).toContainText("Работает", { timeout: 10000 });
    await model.getByText("Работа и простой", { exact: true }).click();
    await expect(model).toContainText("При работе моделей");
    finish?.();
    await expect(model).not.toContainText("Работает", { timeout: 10000 });
    await expect(model).toContainText("Завершено операций: 1");
    await page
      .locator(".resource-panel")
      .evaluate((element) => (element.scrollTop = 0));
    await page.screenshot({
      path: "local/screenshots/monitor.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 950, height: 700 });
    await page.screenshot({
      path: "local/screenshots/monitor-narrow.png",
      fullPage: true,
    });
    const wide = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(wide).toBe(false);
    expect(errors).toEqual([]);
  } finally {
    finish?.();
    await app.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
