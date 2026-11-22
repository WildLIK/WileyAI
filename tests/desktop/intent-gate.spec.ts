import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("C7 flag is off, persists explicitly and leaves model/voice/legacy settings intact", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-c7-settings-"));
  const launch = () => electron.launch({ args: ["--mute-audio", "."], env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data } });
  let app = await launch();
  try {
    let page = await app.firstWindow();
    await expect(page.getByRole("heading", { name: "Привет, я Уайли." })).toBeVisible();
    const before = await page.evaluate(async () => {
      const c = await window.wiley.connection();
      return (await fetch(c.url+"/settings", { headers:{ Authorization:"Bearer "+c.token } })).json();
    });
    expect(before.intent_gate).toBe(false);
    await page.getByRole("button", { name:"⚙ Настройки", exact:true }).click();
    await page.getByRole("tab", { name:"Мозг", exact:true }).click();
    const flag = page.getByRole("switch", { name:"Интеллектуальное понимание команд", exact:true });
    await expect(flag).not.toBeChecked();await flag.check();
    await page.getByRole("button", { name:"Сохранить", exact:true }).click();
    await expect(page.getByRole("status")).toHaveText("Настройки сохранены");
    await app.close();app=await launch();page=await app.firstWindow();
    await expect(page.getByRole("heading", { name:"Привет, я Уайли." })).toBeVisible();
    const after = await page.evaluate(async () => {
      const c = await window.wiley.connection();
      return (await fetch(c.url+"/settings", { headers:{ Authorization:"Bearer "+c.token } })).json();
    });
    expect(after).toEqual({ ...before, intent_gate:true });
    await page.getByRole("button", { name:"⚙ Настройки", exact:true }).click();
    await page.getByRole("tab", { name:"Мозг", exact:true }).click();
    await expect(page.getByRole("switch", { name:"Интеллектуальное понимание команд", exact:true })).toBeChecked();
  } finally { await app.close(); }
});
