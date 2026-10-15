import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("local dialogue: clarification, reschedule, notes, live window updates and durable draft", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-workflows-"));
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
    const chat = await app.firstWindow();
    await expect(
      chat.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const opened = app.waitForEvent("window");
    await chat.evaluate(() => window.wiley.showWindow("settings"));
    const tasks = await opened;
    await tasks.getByRole("button", { name: "◷ Задачи" }).click();
    await send(chat, "Напомни купить хлеб", "Пока запись не создана");
    await expect(tasks.locator(".alias-row")).toHaveCount(0);
    await send(chat, "завтра в 11", "Напоминание создано");
    const row = tasks.locator(".alias-row").filter({ hasText: "купить хлеб" });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("11:00");
    await send(chat, "Перенеси на 12", "Перенёс");
    await expect(row).toContainText("12:00");
    await expect(tasks.locator(".alias-row")).toHaveCount(1);
    await tasks.getByRole("button", { name: "▤ Заметки" }).click();
    await send(
      chat,
      "Создай заметку Покупки: хлеб и молоко",
      "Создал заметку «Покупки»",
    );
    await expect(
      tasks.getByRole("heading", { name: "Покупки", exact: true }),
    ).toBeVisible();
    await expect(
      tasks.getByText("хлеб и молоко", { exact: true }),
    ).toBeVisible();
    await send(chat, "Отмени это напоминание", "Отменил");
    await tasks.getByRole("button", { name: "◷ Задачи" }).click();
    await expect(tasks.locator(".alias-row")).toHaveCount(0);
    await send(chat, "Напомни проверить сборку", "Когда напомнить");
    await chat.screenshot({
      path: "local/screenshots/workflows.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const chat = await app.firstWindow();
    await expect(
      chat.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await send(chat, "завтра в 14", "Напоминание создано");
    await chat.getByRole("button", { name: "◷ Задачи" }).click();
    await expect(chat.locator(".alias-row")).toHaveCount(1);
    await expect(chat.locator(".alias-row")).toContainText("проверить сборку");
    await expect(chat.locator(".alias-row")).toContainText("14:00");
  } finally {
    await app.close();
  }
});
