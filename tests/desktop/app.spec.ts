import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("desktop: local core, persistent memory, settings, model catalog and avatar window", async () => {
  const data = await mkdtemp(join(tmpdir(), "wileyai-e2e-"));
  const app = await electron.launch({
    args: ["."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    timeout: 30000,
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.getByRole("button", { name: "◎ Память" }).click();
    await page
      .getByLabel("Новая запись памяти")
      .fill("E2E: владелец предпочитает русский язык");
    await page.getByRole("button", { name: "Запомнить", exact: true }).click();
    await expect(
      page.getByText("E2E: владелец предпочитает русский язык", {
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "⚙ Настройки" }).click();
    await page.getByLabel("Имя", { exact: true }).fill("Уайли Тест");
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Настройки сохранены");
    await page.getByRole("button", { name: "⬡ Модели" }).click();
    await expect(
      page.getByRole("heading", { name: "Qwen 3.5 · 4B", exact: true }),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Озвучка" }).click();
    await expect(
      page.getByRole("heading", {
        name: "Silero · русский голос",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Qwen 3.5 · 4B", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("tab", { name: "Распознавание голоса" }).click();
    await expect(
      page.getByRole("heading", { name: "Whisper · small", exact: true }),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Мозг" }).click();
    await page.screenshot({
      path: "local/screenshots/models.png",
      fullPage: true,
    });
    await page.getByRole("button", { name: "◷ Задачи" }).click();
    await page
      .getByLabel("Название", { exact: true })
      .fill("Проверить первую версию");
    await page.getByRole("button", { name: "Добавить", exact: true }).click();
    await expect(
      page.getByText("Проверить первую версию", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "▤ Заметки" }).click();
    await page.getByLabel("Название", { exact: true }).fill("Идеи WileyAI");
    await page
      .getByLabel("Содержание", { exact: true })
      .fill("Голос, память и свой персонаж");
    await page.getByRole("button", { name: "Добавить", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Идеи WileyAI" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "✳ Возможности" }).click();
    await expect(
      page.getByRole("heading", {
        name: "Календарь и планирование",
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "◈ Общение" }).click();
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Запомни: второе проверенное воспоминание");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(
      page.getByText(
        "Запомнил. Посмотреть и удалить запись можно в разделе «Память».",
      ),
    ).toBeVisible();
    await page.screenshot({
      path: "local/screenshots/chat.png",
      fullPage: true,
    });
    const avatarWindow = app.waitForEvent("window");
    await page.getByRole("button", { name: "◈ Аватар", exact: true }).click();
    const avatar = await avatarWindow;
    await expect(
      avatar.getByRole("button", { name: "Открыть чат", exact: true }),
    ).toBeVisible();
    await avatar.close();
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
  const again = await electron.launch({
    args: ["."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await again.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли Тест." }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Запомнил. Посмотреть и удалить запись можно в разделе «Память».",
      ),
    ).toBeVisible();
  } finally {
    await again.close();
  }
});
