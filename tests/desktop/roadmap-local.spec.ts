import { test, expect, _electron as electron } from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("local roadmap: scoped semantic sources, internet/voice settings and reversible background preferences", async () => {
  const server = createServer(async (req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.method === "GET") {
      res.end(
        JSON.stringify({
          models: [{ name: "embeddinggemma:300m", digest: "fixture-weights" }],
        }),
      );
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    res.end(
      JSON.stringify({
        embeddings: body.input.map((text: string) =>
          /автомобиль|машина|транспорт/i.test(text)
            ? [1, 0, 0.01]
            : [0, 1, 0.01],
        ),
      }),
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing port");
  const data = await mkdtemp(join(tmpdir(), "wiley-roadmap-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
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
          embedding_enabled: true,
          embedding_base_url: `http://127.0.0.1:${port}`,
        }),
      });
      await fetch(url + "/memories", {
        method: "POST",
        headers,
        body: JSON.stringify({ text: "Мой автомобиль красный" }),
      });
      await fetch(url + "/memories", {
        method: "POST",
        headers,
        body: JSON.stringify({ text: "Любимый напиток кофе" }),
      });
      const form = new FormData();
      form.append(
        "file",
        new Blob(["Автомобиль требует замены масла."], { type: "text/plain" }),
        "Транспорт.txt",
      );
      await fetch(url + "/documents", {
        method: "POST",
        headers: { Authorization: "Bearer " + token },
        body: form,
      });
    }, address.port);
    await page.reload();
    await page.locator(".nav-item").filter({ hasText: "Модели" }).click();
    await page.getByRole("tab", { name: /Семантический поиск/ }).click();
    await page
      .getByRole("button", { name: "Обновить индекс этого пространства" })
      .click();
    await expect(page.getByText(/Индекс построен/)).toBeVisible({ timeout: 20000 });
    await page.locator(".nav-item").filter({ hasText: "Память" }).click();
    await page.getByLabel("Поиск по памяти", { exact: true }).fill("машина");
    await expect(
      page.getByText("Результаты поиска по смыслу", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Мой автомобиль красный", { exact: true }).first(),
    ).toBeVisible();
    await expect(
      page.getByText("Любимый напиток кофе", { exact: true }),
    ).toHaveCount(0);
    await page.locator(".nav-item").filter({ hasText: "Настройки" }).click();
    await page.getByRole("tab", { name: /Поиск/ }).click();
    await page.getByLabel("Читать публичные страницы по моей ссылке").check();
    await page.getByLabel("Получать погоду через Open-Meteo").check();
    await page
      .getByLabel("Город для погоды", { exact: true })
      .fill("Екатеринбург, Россия");
    await page
      .getByLabel("DNS для чтения страниц, погоды и курсов")
      .selectOption("cloudflare");
    await page.getByRole("tab", { name: /Микрофон и разговор/ }).click();
    await page
      .getByLabel("Экспериментально: перебивать озвучку обращением по имени")
      .check();
    await page.getByLabel("Максимальная длина реплики, секунд").fill("90");
    await page.getByRole("tab", { name: /Данные и копии/ }).click();
    await expect(
      page.getByLabel("Запускать WileyAI при входе в Windows"),
    ).toBeDisabled();
    await page.getByLabel("Тихие часы уведомлений").check();
    await page.getByLabel("Начало", { exact: true }).fill("00:00");
    await page.getByLabel("Окончание", { exact: true }).fill("00:00");
    await page
      .getByLabel("Автоматические резервные копии", { exact: true })
      .selectOption("daily");
    await page.getByLabel("Время копирования", { exact: true }).fill("00:00");
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect
      .poll(
        async () =>
          page.evaluate(async () => {
            const { url, token } = await window.wiley.connection();
            return (
              (
                await (
                  await fetch(url + "/background", {
                    headers: { Authorization: "Bearer " + token },
                  })
                ).json()
              ).path || ""
            );
          }),
        { timeout: 12000 },
      )
      .not.toBe("");
    const config = await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      return (
        await fetch(url + "/settings", {
          headers: { Authorization: "Bearer " + token },
        })
      ).json();
    });
    expect(config.web_dns).toBe("cloudflare");
    expect(config.conversation_max_seconds).toBe(90);
    expect(config.conversation_barge_in).toBe(true);
    await page.reload();
    await page.locator(".nav-item").filter({ hasText: "Настройки" }).click();
    await page.getByRole("tab", { name: /Поиск/ }).click();
    await expect(
      page.getByLabel("Город для погоды", { exact: true }),
    ).toHaveValue("Екатеринбург, Россия");
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
