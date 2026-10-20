import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, readFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("contacts and mail: recipient picker, attachment persistence, reviewed remote draft", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-communications-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.getByRole("button", { name: "♧ Контакты", exact: true }).click();
    await page.getByLabel("Имя", { exact: true }).fill("Тестовый получатель");
    await page.getByLabel("Email", { exact: true }).fill("reader@example.test");
    await page
      .getByRole("button", { name: "Сохранить контакт", exact: true })
      .click();
    await expect(
      page.locator(".mail-item").filter({ hasText: "Тестовый получатель" }),
    ).toBeVisible();
    const status = {
      configured: true,
      connected: true,
      pending: false,
      error: "",
      drafts_enabled: true,
      send_enabled: false,
      binding: { account: "owner@example.test", epoch: "fixture" },
    };
    await page.route("**/mail/status*", (route) =>
      route.fulfill({ json: status }),
    );
    await page.route("**/mail/drafts/*/delivery*", (route) =>
      route.fulfill({ json: null }),
    );
    let saves = 0;
    await page.route(/\/mail\/drafts\/[^/]+\/remote(?:\?|$)/, (route) =>
      route.fulfill({
        json: saves ? { state: "ready", remote_id: "draft-1" } : null,
      }),
    );
    await page.route("**/mail/drafts/*/remote-preview*", (route) =>
      route.fulfill({
        json: {
          ticket: "remote-ticket",
          account: "owner@example.test",
          remote_changed: true,
          remote_text: "Другая версия Gmail",
          to_addresses: ["reader@example.test"],
          cc_addresses: [],
          bcc_addresses: [],
          subject: "Письмо с вложением",
          body: "Проверенный текст",
          attachments: [{ name: "файл.txt", size: 12 }],
        },
      }),
    );
    await page.route("**/mail/remote-save*", async (route) => {
      saves++;
      await route.fulfill({ json: { state: "ready", remote_id: "draft-1" } });
    });
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await page
      .getByLabel("Добавить получателя из контактов")
      .selectOption({ label: "Тестовый получатель · reader@example.test" });
    await expect(page.getByLabel("Кому", { exact: true })).toHaveValue(
      "reader@example.test",
    );
    await page
      .getByLabel("Тема письма", { exact: true })
      .fill("Письмо с вложением");
    await page
      .getByLabel("Текст письма", { exact: true })
      .fill("Проверенный текст");
    await page
      .getByLabel("Добавить вложения (до 5 МБ на файл, всего 10 МБ)")
      .setInputFiles({
        name: "файл.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("Приложение"),
      });
    await page
      .getByRole("button", { name: "Сохранить черновик", exact: true })
      .click();
    await expect(
      page.getByText("Черновик сохранён в WileyAI", { exact: true }),
    ).toBeVisible();
    const eml = join(data, "attachment-draft.eml");
    await app.evaluate(({ dialog }, path) => {
      dialog.showSaveDialog = async () => ({ canceled: false, filePath: path });
    }, eml);
    await page
      .getByRole("button", { name: "Сохранить файл EML", exact: true })
      .click();
    await expect(
      page.getByText("Файл черновика сохранён: " + eml, { exact: true }),
    ).toBeVisible();
    expect(await readFile(eml, "utf8")).toContain(
      Buffer.from("Приложение").toString("base64"),
    );
    await page.getByRole("button", { name: "▤ Заметки", exact: true }).click();
    await page.getByRole("button", { name: "✉ Почта", exact: true }).click();
    await expect(page.getByLabel("Текст письма", { exact: true })).toHaveValue(
      "Проверенный текст",
    );
    const button = page.getByRole("button", {
      name: "Сравнить и сохранить в Gmail",
      exact: true,
    });
    await button.click();
    await expect(
      page.getByText("Другая версия Gmail", { exact: true }),
    ).toBeVisible();
    const confirm = page.getByRole("button", {
      name: "Подтвердить сохранение в Gmail",
      exact: true,
    });
    await expect(confirm).toBeDisabled();
    expect(saves).toBe(0);
    await page
      .getByRole("button", { name: "Отменить сохранение", exact: true })
      .click();
    expect(saves).toBe(0);
    await button.click();
    await page.getByLabel("Подтверждаю сохранение этой версии в Gmail").check();
    await confirm.click();
    await expect.poll(() => saves).toBe(1);
    await expect(confirm).toBeHidden();
    expect(errors).toEqual([]);
    await mkdir(join(process.cwd(), "local", "review"), { recursive: true });
    await page.screenshot({
      path: join(process.cwd(), "local", "review", "communications-mail.png"),
      fullPage: true,
    });
  } finally {
    await app.close();
  }
});

test("Telegram: login with two-factor, inert history, cached tab, reviewed text send", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-telegram-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    let status = {
      configured: false,
      connected: false,
      pending: false,
      password_required: false,
      account: "",
    };
    let sends = 0,
      dialogReads = 0;
    await page.route("**/telegram/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let result: unknown = status;
      if (path.endsWith("/client"))
        result = status = { ...status, configured: true };
      if (path.endsWith("/login"))
        result = status = { ...status, pending: true };
      if (path.endsWith("/code"))
        result = status = { ...status, password_required: true };
      if (path.endsWith("/password"))
        result = status = {
          ...status,
          connected: true,
          pending: false,
          password_required: false,
          account: "fixture",
        };
      if (path.endsWith("/dialogs")) {
        dialogReads++;
        result = [
          { ticket: "dialog-1", title: "Проверенный адресат", unread: 1 },
        ];
      }
      if (path.includes("/messages/"))
        result = {
          messages: [
            {
              id: 1,
              text: "<script>Это текст сообщения</script>",
              date: new Date().toISOString(),
              outgoing: false,
              media: false,
            },
          ],
          next_before: 0,
        };
      if (path.endsWith("/preview"))
        result = {
          ticket: "send-1",
          recipient: "Проверенный адресат",
          text: route.request().postDataJSON().text,
        };
      if (path.endsWith("/send")) {
        sends++;
        result = { id: "send-1", state: "sent", message_id: 77 };
      }
      if (path.endsWith("/outbox"))
        result = sends
          ? [
              {
                id: "send-1",
                title: "Проверенный адресат",
                text: "Проверенное сообщение",
                state: "sent",
                message_id: 77,
                created: new Date().toISOString(),
              },
            ]
          : [];
      await route.fulfill({ json: result });
    });
    await page.getByRole("button", { name: "➤ Telegram", exact: true }).click();
    await page.getByLabel("Telegram api_id", { exact: true }).fill("12345");
    await page
      .getByLabel("Telegram api_hash", { exact: true })
      .fill("a".repeat(32));
    await page
      .getByRole("button", {
        name: "Сохранить настройки Telegram",
        exact: true,
      })
      .click();
    await page
      .getByLabel("Номер Telegram", { exact: true })
      .fill("+79990000000");
    await page
      .getByRole("button", { name: "Получить код Telegram", exact: true })
      .click();
    await page.getByLabel("Код Telegram", { exact: true }).fill("12345");
    await page
      .getByRole("button", { name: "Подтвердить код Telegram", exact: true })
      .click();
    await page
      .getByLabel("Пароль двухэтапной проверки Telegram", { exact: true })
      .fill("fixture-password");
    await page
      .getByRole("button", { name: "Войти в Telegram", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Загрузить диалоги", exact: true })
      .click();
    await page
      .locator("button.mail-item")
      .filter({ hasText: "Проверенный адресат" })
      .click();
    await expect(
      page.getByText("<script>Это текст сообщения</script>", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("textbox", { name: "Сообщение Telegram", exact: true })
      .fill("Проверенное сообщение");
    await page.getByRole("button", { name: "▤ Заметки", exact: true }).click();
    await page.getByRole("button", { name: "➤ Telegram", exact: true }).click();
    await page.getByRole("button", { name: "♧ Контакты", exact: true }).click();
    await page.getByRole("button", { name: "➤ Telegram", exact: true }).click();
    await expect(
      page.getByRole("textbox", { name: "Сообщение Telegram", exact: true }),
    ).toHaveValue("Проверенное сообщение");
    expect(dialogReads).toBe(1);
    const review = page.getByRole("button", {
      name: "Проверить сообщение Telegram",
      exact: true,
    });
    await review.click();
    const confirm = page.getByRole("button", {
      name: "Подтвердить отправку Telegram",
      exact: true,
    });
    await expect(confirm).toBeDisabled();
    await page
      .getByRole("button", { name: "Отменить сообщение", exact: true })
      .click();
    expect(sends).toBe(0);
    await review.click();
    await page.getByLabel("Получатель и текст Telegram проверены").check();
    await confirm.click();
    await expect.poll(() => sends).toBe(1);
    await expect(
      page.getByRole("textbox", { name: "Сообщение Telegram", exact: true }),
    ).toHaveValue("");
    await expect(
      page
        .getByText("Telegram подтвердил сообщение №77", { exact: true })
        .first(),
    ).toBeVisible();
    expect(errors).toEqual([]);
    await mkdir(join(process.cwd(), "local", "review"), { recursive: true });
    await page.screenshot({
      path: join(
        process.cwd(),
        "local",
        "review",
        "communications-telegram.png",
      ),
      fullPage: true,
    });
  } finally {
    await app.close();
  }
});
