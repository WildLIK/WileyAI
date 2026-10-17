import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("distribution: component progress/cancel/restart and private GitHub update preferences", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-distribution-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    let job: {
      component: string;
      state: string;
      stage: string;
      progress: number | null;
    } | null = null;
    let installed = false;
    const component = () => ({
      items: [
        {
          id: "piper",
          name: "Piper",
          description: "Быстрая озвучка",
          size: "300 МБ",
          installed,
          available: false,
          restart: installed,
        },
      ],
      job,
    });
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/components(?:\/.*)?$/,
      async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith("/install"))
          job = {
            component: "piper",
            state: "running",
            stage: "Загрузка пакетов",
            progress: null,
          };
        if (path.endsWith("/cancel"))
          job = {
            component: "piper",
            state: "cancelled",
            stage: "Установка отменена",
            progress: null,
          };
        await route.fulfill({ json: component() });
      },
    );
    await page.getByRole("button", { name: "⬡ Модели", exact: true }).click();
    await page.getByRole("button", { name: "Установить", exact: true }).click();
    await expect(
      page.getByRole("progressbar", { name: "Установка компонента" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Отменить установку" }).click();
    await expect(page.locator(".component-job")).toContainText(
      "Установка отменена",
    );
    await page.getByRole("button", { name: "Установить", exact: true }).click();
    installed = true;
    job = {
      component: "piper",
      state: "done",
      stage: "Установлено",
      progress: 100,
    };
    await expect(
      page.getByRole("button", { name: "Перезапустить", exact: true }),
    ).toBeVisible();
    await page.setViewportSize({ width: 760, height: 760 });
    expect(
      await page
        .locator(".scroll-page")
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    await page.screenshot({ path: "local/screenshots/components-760.png" });

    let state = {
      current_version: "0.2.0",
      automatic: true,
      checked_at: null as number | null,
      available: null as { version: string; url: string } | null,
      dismissed: "",
      checking: false,
      has_key: false,
      error: "",
    };
    let savedKey = "";
    await page.route(
      /http:\/\/127\.0\.0\.1:\d+\/updates(?:\/.*)?$/,
      async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith("/check"))
          state = {
            ...state,
            checked_at: Date.now() / 1000,
            available: {
              version: "v0.3.0",
              url: "https://github.com/WildLIK/WileyAI/releases/tag/v0.3.0",
            },
          };
        if (path.endsWith("/dismiss")) state.dismissed = "v0.3.0";
        if (route.request().method() === "PUT") {
          const body = route.request().postDataJSON();
          state.automatic = body.automatic;
          if (body.token !== undefined) {
            savedKey = body.token;
            state.has_key = Boolean(savedKey);
          }
        }
        await route.fulfill({ json: state });
      },
    );
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page
      .getByRole("tab", { name: "Данные и копии", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Проверить обновления", exact: true })
      .click();
    await expect(page.locator(".update-notice")).toContainText("v0.3.0");
    await page
      .getByRole("button", { name: "Скрыть уведомление об обновлении" })
      .click();
    await expect(page.locator(".update-notice")).toHaveCount(0);
    await page.getByLabel("Проверять обновления автоматически").uncheck();
    expect(state.automatic).toBe(false);
    await page
      .getByText("Доступ к закрытому репозиторию", { exact: false })
      .click();
    await page
      .getByLabel("Ключ GitHub", { exact: true })
      .fill("github_pat_TEST_ONLY");
    await page.getByRole("button", { name: "Сохранить ключ GitHub" }).click();
    await expect(page.getByLabel("Ключ GitHub", { exact: true })).toHaveValue(
      "",
    );
    expect(savedKey).toBe("github_pat_TEST_ONLY");
    await expect(
      page.getByText("Доступ к закрытому репозиторию · ключ сохранён"),
    ).toBeVisible();
    await page.screenshot({ path: "local/screenshots/updates-760.png" });
  } finally {
    await app.close();
  }
});
