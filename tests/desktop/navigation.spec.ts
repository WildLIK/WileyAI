import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

for (const theme of ["aurora", "nebula"]) {
  test(`navigation: one active page after repeated and rapid tab changes (${theme})`, async () => {
    const data = await mkdtemp(join(tmpdir(), "wiley-navigation-"));
    const app = await electron.launch({
      args: ["--mute-audio", "."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
    try {
      const page = await app.firstWindow();
      // This fixture deliberately leaves an unsaved mail editor. Allow only
      // its test windows to close without the normal beforeunload prompt.
      await app.evaluate(({ BrowserWindow }) => {
        for (const window of BrowserWindow.getAllWindows())
          window.webContents.on("will-prevent-unload", (event) =>
            event.preventDefault(),
          );
      });
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (
          /same key|Encountered two children|removeChild/.test(message.text())
        )
          errors.push(message.text());
      });
      await expect(
        page.getByRole("heading", { name: "Привет, я Уайли." }),
      ).toBeVisible();
      await page.evaluate(async (theme) => {
        const { url, token } = await window.wiley.connection();
        const headers = {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        };
        const settings = await (
          await fetch(url + "/settings", { headers })
        ).json();
        const response = await fetch(url + "/settings", {
          method: "PUT",
          headers,
          body: JSON.stringify({ ...settings, ui_theme: theme }),
        });
        if (!response.ok) throw new Error("Fixture settings failed");
      }, theme);
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const nav = page.getByRole("navigation");
      const main = page.getByRole("main");
      // Reproduce the reported documents -> calendar -> Telegram sequence
      // before visiting Mail, whose persistent component is also a sibling.
      const tabs = [
        ["▧ Документы", "Документы"],
        ["▦ Календарь", "Календарь"],
        ["➤ Telegram", "Telegram"],
        ["✉ Почта", "Почта и черновики"],
        ["◎ Память", "Что я помню о вас"],
        ["♧ Контакты", "Контакты"],
        ["▤ Заметки", "Заметки и списки"],
        ["◷ Задачи", "Задачи и напоминания"],
        ["⬡ Модели", "Модели и голос"],
        ["⌘ Команды", "Команды и сценарии"],
        ["⌁ Интеграции", "Интеграции"],
        ["✳ Возможности", "Возможности"],
        ["▥ Нагрузка", "Нагрузка"],
        ["⚙ Настройки", "Настройки ассистента"],
      ];
      for (let round = 0; round < 2; round++) {
        for (const [label, heading] of tabs) {
          await nav.getByRole("button", { name: label, exact: true }).click();
          await expect(
            main.getByRole("heading", { name: heading, exact: true }),
          ).toBeVisible();
          await expect(main.locator(".page:visible")).toHaveCount(1);
          // An inactive page must not remain attached as a visible orphan.
          await expect(main.locator(".page:visible h1")).toHaveText([heading]);
          if (label === "✉ Почта" && round === 0)
            await page
              .getByLabel("Текст письма", { exact: true })
              .fill("Черновик между вкладками");
        }
      }
      await nav.getByRole("button", { name: "✉ Почта", exact: true }).click();
      await expect(
        page.getByRole("textbox", { name: "Текст письма", exact: true }),
      ).toHaveValue("Черновик между вкладками");
      // Leave each render one frame to catch reconciliation during fast clicks.
      await page.evaluate(async () => {
        for (const label of [
          "▧ Документы",
          "▦ Календарь",
          "◎ Память",
          "✉ Почта",
          "▦ Календарь",
          "➤ Telegram",
        ]) {
          const button = [
            ...document.querySelectorAll<HTMLButtonElement>("nav button"),
          ].find((node) => node.getAttribute("aria-label") === label);
          if (!button) throw new Error("Missing navigation button");
          button.click();
          await new Promise(requestAnimationFrame);
        }
      });
      await expect(main.locator(".page:visible")).toHaveCount(1);
      await expect(main.locator(".page:visible h1")).toHaveText(["Telegram"]);
      await page.getByLabel("Telegram api_id", { exact: true }).fill("12345");
      await page
        .getByLabel("Telegram api_hash", { exact: true })
        .fill("a".repeat(32));
      await nav
        .getByRole("button", { name: "▦ Календарь", exact: true })
        .click();
      await nav
        .getByRole("button", { name: "➤ Telegram", exact: true })
        .click();
      await expect(
        page.getByLabel("Telegram api_id", { exact: true }),
      ).toHaveValue("12345");
      await expect(
        page.getByRole("button", {
          name: "Сохранить настройки Telegram",
          exact: true,
        }),
      ).toBeEnabled();
      await expect(main.locator(".page:visible h1")).toHaveText(["Telegram"]);
      await nav.getByRole("button", { name: "✉ Почта", exact: true }).click();
      await page
        .getByRole("button", { name: "Сохранить черновик", exact: true })
        .click();
      await expect(
        page.getByText("Черновик сохранён в WileyAI", { exact: true }),
      ).toBeVisible();
      await nav
        .getByRole("button", { name: "➤ Telegram", exact: true })
        .click();
      expect(errors).toEqual([]);
      await mkdir(join(process.cwd(), "local", "review"), { recursive: true });
      await page.screenshot({
        path: join(process.cwd(), "local", "review", `navigation-${theme}.png`),
        fullPage: true,
      });
    } finally {
      await app.close();
    }
  });
}
