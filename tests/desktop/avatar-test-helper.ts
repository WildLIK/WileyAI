import { expect, type ElectronApplication, type Page } from "@playwright/test";

export async function openAvatarTest(app: ElectronApplication, page: Page) {
  await page.getByRole("button", { name: "⚙ Настройки", exact: true }).click();
  await page.getByRole("tab", { name: "Аватар", exact: true }).click();
  const opened = app.waitForEvent("window");
  await page
    .getByRole("button", { name: "Тест эмоций и поз", exact: true })
    .click();
  const tool = await opened;
  await expect(
    tool.getByRole("region", { name: "Проверка эмоций и жестов", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
  return tool;
}
