import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function tasks(page: Page) {
  return page.evaluate(async () => {
    const { url, token } = await window.wiley.connection();
    return (
      await fetch(url + "/tasks", {
        headers: { Authorization: "Bearer " + token },
      })
    ).json();
  });
}

test("recurring reminders: form, weekdays, stop/edit/resume, restart and Russian command", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-repeats-"));
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
    await page.getByRole("button", { name: "◷ Задачи", exact: true }).click();
    await page.getByLabel("Название", { exact: true }).fill("Зарядка");
    await page.getByLabel("Тип", { exact: true }).selectOption("reminder");
    await page.getByLabel("Повтор", { exact: true }).selectOption("weekly");
    for (const day of [
      "Понедельник",
      "Вторник",
      "Среда",
      "Четверг",
      "Пятница",
      "Суббота",
      "Воскресенье",
    ]) {
      await page.getByLabel(day, { exact: true }).uncheck();
    }
    await expect(
      page.getByRole("button", { name: "Добавить", exact: true }),
    ).toBeDisabled();
    await page.getByLabel("Понедельник", { exact: true }).check();
    await page.getByLabel("Среда", { exact: true }).check();
    const due = await page.evaluate(() => {
      const value = new Date(Date.now() + 7 * 86400000);
      value.setHours(10, 0, 0, 0);
      return new Date(value.getTime() - value.getTimezoneOffset() * 60000)
        .toISOString()
        .slice(0, 16);
    });
    await page.getByLabel("Ближайшее напоминание", { exact: true }).fill(due);
    await page.getByRole("button", { name: "Добавить", exact: true }).click();
    const row = page.getByRole("group", { name: "Зарядка", exact: true });
    await expect(row).toContainText("по пн, ср");
    let [task] = await tasks(page);
    const rule = JSON.parse(task.recurrence);
    expect(rule.weekdays).toEqual([0, 2]);
    // The API omits the default UTC field from its compact stored JSON.
    expect(rule.timezone ?? "UTC").toBe(
      await page.evaluate(
        () => Intl.DateTimeFormat().resolvedOptions().timeZone,
      ),
    );
    await row
      .getByRole("button", { name: "Остановить серию", exact: true })
      .click();
    await expect(row).toContainText("серия остановлена");
    await row.getByRole("button", { name: "Изменить", exact: true }).click();
    await expect(page.getByLabel("Повтор", { exact: true })).toHaveValue(
      "weekly",
    );
    await expect(page.getByLabel("Среда", { exact: true })).toBeChecked();
    await page.getByLabel("Пятница", { exact: true }).check();
    await page
      .getByRole("button", { name: "Сохранить изменения", exact: true })
      .click();
    await expect(row).toContainText("по пн, ср, пт");
    await expect(row).toContainText("серия остановлена");
    [task] = await tasks(page);
    expect(task.done).toBe(1);
    expect(JSON.parse(task.recurrence).weekdays).toEqual([0, 2, 4]);
    await row
      .getByRole("button", { name: "Возобновить серию", exact: true })
      .click();
    await expect(row).not.toContainText("серия остановлена");
    await page.setViewportSize({ width: 1100, height: 850 });
    await row.getByRole("button", { name: "Изменить", exact: true }).click();
    await page.screenshot({
      path: "local/screenshots/repeats.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
  app = await launch();
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("button", { name: "Начать разговор", exact: true }),
    ).toBeVisible();
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Напомни по будням в 10 проверить почту");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("по будням");
    expect((await tasks(page)).length).toBe(2);
    await page.getByRole("button", { name: "◷ Задачи", exact: true }).click();
    const row = page.getByRole("group", { name: "Зарядка", exact: true });
    await expect(row).toContainText("по пн, ср, пт");
    await row.getByRole("button", { name: "Изменить", exact: true }).click();
    await page.getByLabel("Повтор", { exact: true }).selectOption("none");
    await page
      .getByRole("button", { name: "Сохранить изменения", exact: true })
      .click();
    await expect(row).not.toContainText("по пн");
    expect(
      (await tasks(page)).find(
        (item: { title: string }) => item.title === "Зарядка",
      ).recurrence,
    ).toBeNull();
    await row.getByRole("button", { name: "Удалить", exact: true }).click();
    await expect(row).toHaveCount(0);
  } finally {
    await app.close();
  }
});
