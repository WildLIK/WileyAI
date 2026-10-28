import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("phone access can be enabled, paired and disabled from settings", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-mobile-"));
  const app = await electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  const page = await app.firstWindow();
  try {
    await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    await page.getByRole("button", { name: "⚙ Настройки", exact: true }).click();
    await page.getByRole("tab", { name: "Телефон", exact: true }).click();
    await page.getByRole("button", { name: "Включить подключение", exact: true }).click();
    await expect(page.getByText(/Подключение включено · порт/)).toBeVisible();
    const addresses = page.getByLabel("Адрес компьютера для телефона");
    if ((await addresses.locator("option").count()) > 1) {
      await page.getByRole("button", { name: "Показать код для телефона" }).click();
      await expect(page.getByRole("img", { name: "Код подключения Android" })).toBeVisible();
    }
    await page.getByRole("button", { name: "Выключить подключение", exact: true }).click();
    await expect(page.getByText("Подключение выключено", { exact: true })).toBeVisible();
  } finally { await app.close(); }
});
