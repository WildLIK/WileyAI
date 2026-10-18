import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function send(page: Page, text: string, expected: string) {
  await page.getByLabel("Сообщение", { exact: true }).fill(text);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(
    page.locator(".message.assistant .message-text").last(),
  ).toContainText(expected);
}

async function items(page: Page) {
  return page.evaluate(async () => {
    const { url, token } = await window.wiley.connection();
    return (
      await fetch(url + "/tasks", {
        headers: { Authorization: "Bearer " + token },
      })
    ).json();
  });
}

test("named tasks: no recent context, numbered choice across restart, stale edit in another window", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-task-selection-"));
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
    await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      for (const days of [1, 2]) {
        const due = new Date(Date.now() + days * 86400000);
        due.setHours(10, 0, 0, 0);
        const response = await fetch(url + "/tasks", {
          method: "POST",
          headers: {
            Authorization: "Bearer " + token,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            title: "Почта",
            kind: "reminder",
            due: due.toISOString(),
          }),
        });
        if (!response.ok) throw new Error("Cannot seed isolated test task");
      }
    });
    await send(
      page,
      "Перенеси напоминание почта на 11",
      "Найдено несколько записей",
    );
    expect(
      (await items(page)).every(
        (item: { due: string }) => new Date(item.due).getHours() === 10,
      ),
    ).toBe(true);
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("Найдено несколько");
    await send(page, "второе", "Перенесла");
    const tasks = await items(page);
    expect(
      tasks.map((item: { due: string }) => new Date(item.due).getHours()),
    ).toEqual([10, 11]);
    await send(page, "Удали напоминание почта", "Найдено несколько");
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await second.getByRole("button", { name: "◷ Задачи", exact: true }).click();
    await second
      .getByRole("group", { name: "Почта", exact: true })
      .first()
      .getByRole("button", { name: "Изменить", exact: true })
      .click();
    await second.getByLabel("Название", { exact: true }).fill("Новая почта");
    await second
      .getByRole("button", { name: "Сохранить изменения", exact: true })
      .click();
    await expect(
      second.getByRole("group", { name: "Новая почта", exact: true }),
    ).toBeVisible();
    await send(page, "1", "Запись изменилась или удалена");
    expect((await items(page)).length).toBe(2);
    await send(page, "Удали напоминание новая почта", "Удалил");
    await expect(
      second.getByRole("group", { name: "Новая почта", exact: true }),
    ).toHaveCount(0);
    await send(page, "Найди напоминание почта", "Выбрана запись");
    await page.screenshot({
      path: "local/screenshots/task-selection.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
});
