import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("semantic command flag defaults off, persists after restart, and preserves voice 3.3 settings", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-semantic-settings-"));
  const launch = () => electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    const before = await page.evaluate(async () => {
      const connection = await window.wiley.connection();
      return (await fetch(connection.url + "/settings", { headers: { Authorization: "Bearer " + connection.token } })).json();
    });
    expect(before.semantic_commands).toBe(false);
    await page.getByRole("button", { name: "⚙ Настройки", exact: true }).click();
    const flag = page.getByRole("checkbox", { name: "Подбор свободных команд (3.4)", exact: true });
    await expect(flag).not.toBeChecked(); await flag.check();
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Настройки сохранены");
    await app.close(); app = await launch(); page = await app.firstWindow();
    await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    const after = await page.evaluate(async () => {
      const connection = await window.wiley.connection();
      return (await fetch(connection.url + "/settings", { headers: { Authorization: "Bearer " + connection.token } })).json();
    });
    expect(after).toEqual({ ...before, semantic_commands: true });
    await page.getByRole("button", { name: "⚙ Настройки", exact: true }).click();
    await expect(page.getByRole("checkbox", { name: "Подбор свободных команд (3.4)", exact: true })).toBeChecked();
  } finally { await app.close(); }
});
