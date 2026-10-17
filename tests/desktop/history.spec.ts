import { test, expect, _electron as electron } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

test("history search: scoped local results, old-message jump, highlighted word, pagination and latest view", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-history-"));
  const seed = JSON.parse(
    execFileSync(
      resolve(".venv/Scripts/python.exe"),
      [
        "-c",
        `
import json,sys
from pathlib import Path
from core.storage import Store
from core.chatspaces import Spaces
from core.config import Settings
s=Store(Path(sys.argv[1])); spaces=Spaces(s)
s.save_settings(Settings(provider="compatible",base_url="http://127.0.0.1:9/v1",model="no-model-used"))
spaces.update_chat(s.conversation_id,"Общие разговоры",None)
s.add_message("user","СОКОЛ-7351 Общее обсуждение")
p=spaces.create_project("Книга"); a=spaces.create_chat(p["id"],"Большая история"); peer=spaces.create_chat(p["id"],"Идеи")
c=s.for_chat(a["id"])
target=c.add_message("assistant","Длинное вступление. "*350+"СОКОЛ-7351 <img src=x onerror=example> Найденный фрагмент.")
for i in range(335): c.add_message("user","Обычная реплика "+str(i)+(" ПОВТОРЕНИЕ" if i<55 else ""))
s.for_chat(peer["id"]).add_message("user","СОКОЛ-7351 Идея внутри книги")
other=spaces.create_project("Личное"); b=spaces.create_chat(other["id"],"Другой проект")
s.for_chat(b["id"]).add_message("user","СОКОЛ-7351 Отдельный проект")
print(json.dumps({"chat":a["id"],"target":target["id"]}))
`,
        data,
      ],
      { encoding: "utf8" },
    ),
  );
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(page.getByLabel("Сообщение", { exact: true })).toBeVisible();
    await page.evaluate(() =>
      localStorage.setItem("wiley-active-chat", "legacy"),
    );
    await page.reload();
    await expect(page.locator(".chat-toolbar h1")).toHaveText(
      "Общие разговоры",
    );
    let modelCalls = 0;
    await page.route("**/chat", async (route) => {
      modelCalls++;
      await route.continue();
    });
    await page
      .getByRole("button", { name: "Поиск в переписке", exact: true })
      .click();
    const dialog = page.getByRole("dialog", {
      name: "Поиск в переписке",
      exact: true,
    });
    const query = dialog.getByLabel("Поиск по сообщениям", { exact: true });
    const scope = dialog.getByLabel("Область поиска переписки", {
      exact: true,
    });
    await expect(query).toBeFocused();
    await query.fill("СОКОЛ-7351");
    await expect(dialog.locator(".history-result")).toHaveCount(1);
    await expect(scope).toHaveValue("space");
    await scope.selectOption("all");
    await expect(dialog.locator(".history-result")).toHaveCount(4);
    await dialog
      .getByLabel("Автор сообщения", { exact: true })
      .selectOption("assistant");
    await expect(dialog.locator(".history-result")).toHaveCount(1);
    await dialog.screenshot({ path: "local/screenshots/history-search.png" });
    await dialog.locator(".history-result").click();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator(".chat-toolbar h1")).toHaveText(
      "Большая история",
    );
    const target = page.locator('[data-message-id="' + seed.target + '"]');
    await expect(target).toHaveClass(/history-hit/);
    await expect(target.locator("mark").first()).toBeInViewport();
    await expect(target.locator("img")).toHaveCount(0);
    expect(await page.locator(".message").count()).toBeLessThanOrEqual(81);
    await expect(page.locator(".history-window-banner")).toBeVisible();
    await page.screenshot({
      path: "local/screenshots/history-message-jump.png",
    });
    // A refresh from another window must preserve the historical view.
    await page.evaluate(() => {
      const channel = new BroadcastChannel("wiley-ui");
      channel.postMessage({ type: "chat-updated" });
      channel.close();
    });
    await expect(target.locator("mark").first()).toBeInViewport();
    await page
      .getByRole("button", {
        name: "Вернуться к последним сообщениям",
        exact: true,
      })
      .click();
    await expect(page.locator(".history-window-banner")).toHaveCount(0);
    await expect(page.locator(".message")).toHaveCount(250);
    await expect(target).toHaveCount(0);
    await expect
      .poll(() =>
        page
          .locator(".messages")
          .evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight),
      )
      .toBeLessThan(5);
    await page.keyboard.press("Control+f");
    await expect(dialog).toBeVisible();
    await expect(scope).toHaveValue("chat");
    await query.fill("ПОВТОРЕНИЕ");
    await expect(dialog.locator(".history-result")).toHaveCount(20);
    await expect(dialog).toContainText("Найдено: 55");
    await dialog
      .getByRole("button", { name: "Следующие совпадения", exact: true })
      .click();
    await expect(dialog).toContainText("21–40");
    await dialog
      .getByRole("button", { name: "Следующие совпадения", exact: true })
      .click();
    await expect(dialog.locator(".history-result")).toHaveCount(15);
    await expect(dialog).toContainText("41–55");
    // A late result for a cancelled request must not replace the current results.
    let release!: () => void, entered!: () => void;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const blocked = new Promise<void>((r) => {
      entered = r;
    });
    await page.route("**/history/search?**", async (route) => {
      if (new URL(route.request().url()).searchParams.get("q") === "ЗАДЕРЖКА") {
        entered();
        await gate;
        await route
          .fulfill({ json: { items: [], total: 999, terms: [] } })
          .catch(() => {});
      } else await route.continue();
    });
    await query.fill("ЗАДЕРЖКА");
    await blocked;
    await query.fill("СОКОЛ-7351");
    await expect(dialog.locator(".history-result")).toHaveCount(1);
    release();
    await expect(dialog).toContainText("Найдено: 1");
    await expect(dialog).not.toContainText("999");
    expect(modelCalls).toBe(0);
    await dialog.locator(".history-result").click();
    await expect(target.locator("mark").first()).toBeInViewport();
    // Sending from a historical view returns to the current end before appending.
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Запомни: я предпочитаю короткие ответы");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".history-window-banner")).toHaveCount(0);
    await expect(page.locator(".message.assistant").last()).toContainText(
      /памят|Запом/,
    );
    await expect(target).toHaveCount(0);
    await page
      .getByRole("button", { name: "Поиск в текущем чате", exact: true })
      .click();
    await query.fill("СОКОЛ-7351");
    await expect(dialog.locator(".history-result")).toHaveCount(1);
    await page.setViewportSize({ width: 850, height: 650 });
    expect(
      await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth),
    ).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await page.reload();
    await page
      .getByRole("button", { name: "Поиск в текущем чате", exact: true })
      .click();
    await query.fill("СОКОЛ-7351");
    await expect(dialog.locator(".history-result")).toHaveCount(1);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
