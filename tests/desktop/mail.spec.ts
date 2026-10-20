import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp, readFile, mkdir } from "node:fs/promises";
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
      const data = await response.json();
      if (!response.ok) throw new Error(JSON.stringify(data));
      return data;
    },
    { route, method, body },
  );
}

test("mail: real local drafts, review-only model text, native EML, stale guard and restart", async () => {
  const prompts: unknown[] = [];
  const server = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ models: [] }));
      return;
    }
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());
    prompts.push(body);
    res.setHeader("Content-Type", "application/x-ndjson");
    res.end(
      JSON.stringify({
        message: {
          content: "Спасибо за предложение. Пришлите, пожалуйста, подробности.",
        },
        done: true,
      }) + "\n",
    );
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("No fixture server");
  const data = await mkdtemp(join(tmpdir(), "wiley-mail-"));
  const file = join(data, "draft.eml");
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
    const config = await api(page, "/settings");
    await api(page, "/settings", "PUT", {
      ...config,
      provider: "ollama",
      base_url: `http://127.0.0.1:${address.port}`,
      model: "mail-fixture",
    });
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await page.getByLabel("Кому", { exact: true }).fill("reader@example.test");
    await page.getByLabel("Копия", { exact: true }).fill("copy@example.test");
    await page
      .getByLabel("Скрытая копия", { exact: true })
      .fill("hidden@example.test");
    await page
      .getByLabel("Тема письма", { exact: true })
      .fill("Ответ на предложение");
    await page
      .getByLabel("Текст письма", { exact: true })
      .fill("Начальный текст");
    await page.getByRole("button", { name: "▤ Заметки", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Почта и черновики" }),
    ).toBeHidden();
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await expect(page.getByLabel("Текст письма", { exact: true })).toHaveValue(
      "Начальный текст",
    );
    await page
      .getByRole("button", { name: "Сохранить черновик", exact: true })
      .click();
    await expect(
      page.getByText("Черновик сохранён в WileyAI", { exact: true }),
    ).toBeVisible();
    await page.getByText("Подготовить текст моделью", { exact: true }).click();
    await page
      .getByLabel("Что написать в письме", { exact: true })
      .fill("Поблагодари и попроси подробности");
    await page
      .getByRole("button", { name: "Составить текст письма", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Предложенный текст" }),
    ).toBeVisible();
    await expect(page.getByLabel("Текст письма", { exact: true })).toHaveValue(
      "Начальный текст",
    );
    await page
      .getByRole("button", { name: "Подставить текст в черновик", exact: true })
      .click();
    await expect(page.getByLabel("Кому", { exact: true })).toHaveValue(
      "reader@example.test",
    );
    await expect(page.getByLabel("Скрытая копия", { exact: true })).toHaveValue(
      "hidden@example.test",
    );
    await expect(
      page.getByRole("button", { name: "Сохранить файл EML", exact: true }),
    ).toBeDisabled();
    await page
      .getByRole("button", { name: "Сохранить черновик", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Сохранить файл EML", exact: true }),
    ).toBeEnabled();
    await app.evaluate(({ dialog }, file) => {
      dialog.showSaveDialog = async () => ({ canceled: false, filePath: file });
    }, file);
    await page
      .getByRole("button", { name: "Сохранить файл EML", exact: true })
      .click();
    await expect(
      page.getByText("Файл черновика сохранён: " + file, { exact: true }),
    ).toBeVisible();
    const eml = await readFile(file, "utf8");
    expect(eml).toContain("X-Unsent: 1");
    expect(eml).toContain("To: reader@example.test");
    expect(eml).toContain("Bcc: hidden@example.test");
    expect(prompts).toHaveLength(1);
    await app.close();
    app = await launch();
    page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await page
      .locator(".mail-item")
      .filter({ hasText: "Ответ на предложение" })
      .click();
    await expect(page.getByLabel("Текст письма", { exact: true })).toHaveValue(
      "Спасибо за предложение. Пришлите, пожалуйста, подробности.",
    );
    const [draft] = await api(page, "/mail/drafts");
    await api(
      page,
      "/mail/drafts/" +
        draft.id +
        "?expected_updated=" +
        encodeURIComponent(draft.updated),
      "PUT",
      {
        to_addresses: ["reader@example.test"],
        cc_addresses: [],
        bcc_addresses: [],
        subject: "Изменено другим окном",
        body: "Новая версия",
      },
    );
    await page
      .getByLabel("Тема письма", { exact: true })
      .fill("Устаревшая правка");
    await page
      .getByRole("button", { name: "Сохранить черновик", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "изменён в другом окне",
    );
    const saved = await api(page, "/mail/drafts/" + draft.id);
    expect(saved.subject).toBe("Изменено другим окном");
    page.once("dialog", (dialog) => dialog.accept());
    await page
      .getByRole("button", { name: "Отменить изменения", exact: true })
      .click();
    expect(errors).toEqual([]);
  } finally {
    await app.close();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

test("mail: Gmail view is inert and reply recipient is visible; local editor works without send", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-mail-reader-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const connection = await page.evaluate(() => window.wiley.connection());
    const summary = {
      ticket: "fixture-summary",
      subject: "Обсуждение встречи",
      sender: "Автор <author@example.test>",
      date: "19.10.2026",
      unread: true,
      snippet: "Здравствуйте",
    };
    let inboxLoads = 0;
    let messageLoads = 0;
    const status = {
      configured: true,
      connected: true,
      pending: false,
      error: "",
      binding: { id: "fixture", account: "owner@example.test" },
      model: "fixture",
      model_location: "local",
    };
    let connected = true;
    const outside: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("tracker.example"))
        outside.push(request.url());
    });
    await page.route("**/mail/status**", (route) =>
      route.fulfill({
        json: connected
          ? status
          : { ...status, connected: false, binding: null },
      }),
    );
    await page.route("**/mail/inbox**", (route) => {
      inboxLoads++;
      return route.fulfill({
        json: {
          messages: [summary],
          next_cursor: null,
          account: "owner@example.test",
          checked_at: new Date().toISOString(),
        },
      });
    });
    await page.route("**/mail/messages/**", (route) => {
      messageLoads++;
      return route.fulfill({
        json: {
          ...summary,
          ticket: "fixture-opened",
          text: 'Текст письма. <img src="https://tracker.example/pixel"><script>window.bad=1</script>',
          reply_to: "reply@example.test",
          reply_addresses: ["reply@example.test"],
          from_html: true,
          truncated: false,
          notes: [],
          attachments: [],
          account: "owner@example.test",
        },
      });
    });
    await page.route("**/mail/reply**", async (route) => {
      const result = await fetch(connection.url + "/mail/drafts", {
        method: "POST",
        headers: {
          Authorization: "Bearer " + connection.token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          to_addresses: ["reply@example.test"],
          subject: "Re: Обсуждение встречи",
          body: "",
        }),
      });
      await route.fulfill({ json: await result.json() });
    });
    await page.route("**/mail/drafts/*/delivery**", (route) =>
      route.fulfill({ json: null }),
    );
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await page
      .getByRole("button", { name: "Загрузить письма", exact: true })
      .click();
    await page
      .locator(".mail-item")
      .filter({ hasText: "Обсуждение встречи" })
      .click();
    const reader = page.getByRole("region", { name: "Просмотр письма" });
    await expect(
      reader.getByText("Адрес ответа: reply@example.test"),
    ).toBeVisible();
    await expect(reader.locator("img, iframe, script")).toHaveCount(0);
    expect(outside).toEqual([]);
    await expect(page.locator(".mail-item[aria-pressed=true]")).toContainText(
      "Обсуждение встречи",
    );
    await page
      .getByLabel("Поиск Gmail", { exact: true })
      .fill("сохранённый поиск");
    const scrollTop = await page.locator(".mail-page").evaluate((element) => {
      element.scrollTop = 170;
      return element.scrollTop;
    });
    await page.getByRole("button", { name: "▤ Заметки", exact: true }).click();
    await expect(reader).toBeHidden();
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await expect(reader).toBeVisible();
    await expect(page.getByLabel("Поиск Gmail", { exact: true })).toHaveValue(
      "сохранённый поиск",
    );
    expect(
      await page.locator(".mail-page").evaluate((element) => element.scrollTop),
    ).toBe(scrollTop);
    expect(inboxLoads).toBe(1);
    expect(messageLoads).toBe(1);
    await page
      .getByRole("button", {
        name: "Подготовить ответ на это письмо",
        exact: true,
      })
      .click();
    await expect(page.getByLabel("Кому", { exact: true })).toHaveValue(
      "reply@example.test",
    );
    await expect(page.getByLabel("Тема письма", { exact: true })).toHaveValue(
      "Re: Обсуждение встречи",
    );
    await expect(page.getByRole("button", { name: /^Отправить/ })).toHaveCount(
      0,
    );
    await mkdir(join(process.cwd(), "local", "review"), { recursive: true });
    await page.screenshot({
      path: join(process.cwd(), "local", "review", "mail.png"),
      fullPage: true,
    });
    connected = false;
    await page.evaluate(() => {
      const bus = new BroadcastChannel("wiley-mail");
      bus.postMessage({ type: "account-changed" });
      bus.close();
    });
    await expect(page.locator(".mail-reader")).toHaveCount(0);
    await expect(page.getByLabel("Кому", { exact: true })).toHaveValue(
      "reply@example.test",
    );
  } finally {
    await app.close();
  }
});

test("mail: saved JSON stays visible and returning from Google exposes inbox access", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-mail-login-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const status = {
      configured: false,
      connected: false,
      pending: false,
      error: "",
      binding: null as { id: string; account: string } | null,
      model: "fixture",
      model_location: "local",
    };
    let bindings = 0;
    await page.route("**/mail/status**", (route) =>
      route.fulfill({ json: status }),
    );
    await page.route("**/mail/gmail/client**", (route) => {
      expect(
        JSON.parse(route.request().postDataJSON().document),
      ).toHaveProperty("installed");
      status.configured = true;
      return route.fulfill({ json: status });
    });
    await page.route("**/mail/gmail/binding**", (route) => {
      expect(route.request().method()).toBe("PUT");
      bindings++;
      status.binding = { id: "fixture-binding", account: "owner@example.test" };
      return route.fulfill({ json: status });
    });
    await page.route("**/mail/inbox**", (route) =>
      route.fulfill({
        json: {
          account: "owner@example.test",
          checked_at: new Date().toISOString(),
          next_cursor: null,
          messages: [
            {
              ticket: "inbox-fixture",
              subject: "Входящее после входа",
              sender: "sender@example.test",
              date: "19.10.2026",
              unread: true,
              snippet: "Письмо доступно для чтения",
            },
          ],
        },
      }),
    );
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    const login = page.getByRole("button", {
      name: "Войти в Gmail через Google",
      exact: true,
    });
    await expect(login).toBeDisabled();
    await expect(
      page.getByRole("heading", { name: "Письма Gmail", exact: true }),
    ).toBeVisible();
    await page.getByText("Настроить доступ Gmail", { exact: true }).click();
    await page.getByLabel("JSON клиента Gmail Desktop app").setInputFiles({
      name: "desktop-client.json",
      mimeType: "application/json",
      buffer: Buffer.from(
        JSON.stringify({ installed: { client_id: "fixture" } }),
      ),
    });
    await expect(
      page.getByText(
        "JSON OAuth-клиента сохранён. Повторно выбирать файл не нужно.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(login).toBeEnabled();
    await page.getByRole("button", { name: "▤ Заметки", exact: true }).click();
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await expect(
      page.getByText(
        "JSON OAuth-клиента сохранён. Повторно выбирать файл не нужно.",
        { exact: true },
      ),
    ).toBeVisible();
    // OAuth can finish while this window has no pending-login state (another
    // window started it, or the browser held focus before the status arrived).
    status.connected = true;
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(
      page.getByText("Вход в Gmail выполнен", { exact: true }),
    ).toBeVisible();
    expect(bindings).toBe(0);
    await page
      .getByRole("button", {
        name: "Использовать Gmail в этом пространстве",
        exact: true,
      })
      .click();
    const load = page.getByRole("button", {
      name: "Загрузить письма",
      exact: true,
    });
    await expect(load).toBeVisible();
    await load.click();
    await expect(
      page.locator(".mail-item").filter({ hasText: "Входящее после входа" }),
    ).toBeVisible();
    expect(bindings).toBe(1);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});

test("mail: Gmail send reviews all recipients, cancels safely and confirms exactly once", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-mail-send-"));
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
    const draft = await api(page, "/mail/drafts", "POST", {
      to_addresses: ["reader@example.test"],
      cc_addresses: ["copy@example.test"],
      bcc_addresses: ["hidden@example.test"],
      subject: "Письмо для проверки отправки",
      body: "Проверенный текст",
    });
    const status = {
      configured: true,
      connected: true,
      send_enabled: true,
      pending: false,
      error: "",
      binding: { id: "fixture", account: "owner@example.test" },
      model: "fixture",
      model_location: "local",
    };
    let receipt: {
      id: string;
      state: string;
      google_id: string;
      revision: string;
    } | null = null;
    let sends = 0;
    await page.route("**/mail/status**", (route) =>
      route.fulfill({ json: status }),
    );
    await page.route("**/mail/drafts/*/delivery**", (route) =>
      route.fulfill({ json: receipt }),
    );
    await page.route("**/mail/drafts/*/send-preview**", (route) => {
      expect(route.request().postDataJSON()).toEqual({
        expected_updated: draft.updated,
      });
      return route.fulfill({
        json: {
          ...draft,
          sender: "owner@example.test",
          ticket: "reviewed-ticket",
        },
      });
    });
    await page.route("**/mail/send**", (route) => {
      expect(route.request().postDataJSON()).toEqual({
        ticket: "reviewed-ticket",
        confirmed: true,
      });
      sends++;
      receipt = {
        id: "fixture-delivery",
        state: "sent",
        google_id: "feed123",
        revision: draft.updated,
      };
      return route.fulfill({ json: receipt });
    });
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await page.locator(".mail-item").filter({ hasText: draft.subject }).click();
    const sendPanel = page.getByRole("region", {
      name: "Отправка через Gmail",
      exact: true,
    });
    await sendPanel
      .getByRole("button", { name: "Проверить перед отправкой", exact: true })
      .click();
    const review = sendPanel.getByRole("region", {
      name: "Проверка письма перед отправкой",
      exact: true,
    });
    await expect(review).toContainText("Кому: reader@example.test");
    await expect(review).toContainText("Копия: copy@example.test");
    await expect(review).toContainText("Скрытая копия: hidden@example.test");
    await expect(review).toContainText("Проверенный текст");
    await expect(
      review.getByRole("button", { name: "Подтвердить и отправить письмо" }),
    ).toBeDisabled();
    await review.getByRole("button", { name: "Отменить отправку" }).click();
    expect(sends).toBe(0);
    await sendPanel
      .getByRole("button", { name: "Проверить перед отправкой", exact: true })
      .click();
    await page
      .getByLabel("Текст письма", { exact: true })
      .fill("Несохранённая правка");
    await expect(review).toHaveCount(0);
    await expect(
      sendPanel.getByRole("button", {
        name: "Проверить перед отправкой",
        exact: true,
      }),
    ).toBeDisabled();
    await page.getByLabel("Текст письма", { exact: true }).fill(draft.body);
    await sendPanel
      .getByRole("button", { name: "Проверить перед отправкой", exact: true })
      .click();
    await review.getByRole("checkbox").check();
    await review
      .getByRole("button", { name: "Подтвердить и отправить письмо" })
      .click();
    await expect(sendPanel.getByRole("status")).toContainText(
      "Google подтвердил письмо",
    );
    await expect(
      sendPanel.getByRole("button", {
        name: "Проверить перед отправкой",
        exact: true,
      }),
    ).toBeDisabled();
    await page.getByRole("button", { name: "▤ Заметки", exact: true }).click();
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await expect(sendPanel.getByRole("status")).toContainText("feed123");
    expect(sends).toBe(1);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
