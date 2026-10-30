import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("pronunciation settings can preview without launching an application", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-pronunciations-"));
  const app = await electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  try {
    const page = await app.firstWindow();
    await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    await page.getByRole("button", { name: /Настройки/ }).first().click();
    await page.getByRole("tab", { name: /Микрофон и разговор/ }).click();
    await expect(page.getByRole("heading", { name: "Мои произношения" })).toBeVisible();
    await page.getByLabel("Фраза для проверки распознавания").fill("Расскажи про Blender");
    await page.getByRole("button", { name: "Проверить фразу" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Ничего не запущено" })).toBeVisible();
    await expect(page.getByText("нет команды открытия")).toBeVisible();
  } finally { await app.close(); }
});
