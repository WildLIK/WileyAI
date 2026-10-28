import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

function clearFixtureCredentials(data: string) {
  const result = spawnSync(
    process.execPath,
    [
      "scripts/python.mjs",
      "-c",
      `
import sys,json,hashlib
from pathlib import Path
import keyring
root=Path(sys.argv[1]).resolve()
assert root.name.startswith('wiley-chatgpt-')
key=hashlib.sha256(str(root).casefold().encode()).hexdigest()
raw=keyring.get_password('WileyAI.ChatGPT',key)
if raw:
 record=json.loads(raw)
 for i in range(min(record['parts'],128)):
  try:keyring.delete_password('WileyAI.ChatGPT',key+':'+record['revision']+':'+str(i))
  except keyring.errors.PasswordDeleteError:pass
 keyring.delete_password('WileyAI.ChatGPT',key)
`,
      data,
    ],
    { windowsHide: true, encoding: "utf8" },
  );
  if (result.status !== 0)
    throw new Error("Could not clean fixture credential registration");
}

async function launch() {
  const data = await mkdtemp(join(tmpdir(), "wiley-chatgpt-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  await app.evaluate(({ shell }) => {
    (globalThis as any).chatgptOpened = [];
    shell.openExternal = async (url: string) => {
      (globalThis as any).chatgptOpened.push(url);
    };
  });
  const page = await app.firstWindow();
  await expect(
    page.getByRole("heading", { name: "Привет, я Уайли." }),
  ).toBeVisible();
  const before = await page.evaluate(async () => {
    const c = await window.wiley.connection();
    return (
      await fetch(c.url + "/settings", {
        headers: { Authorization: "Bearer " + c.token },
      })
    ).json();
  });
  await page.getByRole("button", { name: "⚙ Настройки", exact: true }).click();
  await page.getByRole("tab", { name: /Мозг/ }).click();
  await page.getByLabel("Движок", { exact: true }).selectOption("chatgpt");
  return { app, page, before, data };
}

test("ChatGPT sign-in opens an approved browser URL without an API key and can be cancelled", async () => {
  const { app, page, before, data } = await launch();
  try {
    await expect(
      page.getByLabel("Ключ API", { exact: true }),
    ).not.toBeVisible();
    await page
      .getByRole("button", { name: "Continue with ChatGPT", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Отменить вход", exact: true }),
    ).toBeVisible();
    const urls: string[] = await app.evaluate(
      () => (globalThis as any).chatgptOpened,
    );
    expect(urls).toHaveLength(1);
    const url = new URL(urls[0]);
    expect(url.origin + url.pathname).toBe(
      "https://auth.openai.com/api/accounts/authorize",
    );
    expect(url.searchParams.get("client_id")).toBe("dynamic_agent_client");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("scope")).toContain(
      "chatgpt.tokens.use.direct",
    );
    expect(new URL(url.searchParams.get("redirect_uri")!).hostname).toBe(
      "127.0.0.1",
    );
    await page
      .getByRole("button", { name: "Отменить вход", exact: true })
      .click();
    await expect(
      page.getByText("Аккаунт ChatGPT не подключён", { exact: true }),
    ).toBeVisible();
    const after = await page.evaluate(async () => {
      const c = await window.wiley.connection();
      return (
        await fetch(c.url + "/settings", {
          headers: { Authorization: "Bearer " + c.token },
        })
      ).json();
    });
    expect(after.tts_engine).toBe(before.tts_engine);
    expect(after.stt_model).toBe(before.stt_model);
    expect(after.provider).toBe(before.provider);
  } finally {
    await app.close();
    clearFixtureCredentials(data);
  }
});

test("ChatGPT shows an unfinished registration and the specific login network failure", async () => {
  const { app, page, data } = await launch();
  try {
    await page.route("**/chatgpt/status", (route) =>
      route.fulfill({
        json: {
          connection_id: "a".repeat(64),
          connected: false,
          plan_enabled: false,
          email: "",
          pending: false,
          registration_pending: true,
          error:
            "WileyAI не смог установить соединение с сервером ChatGPT. Этап: получение сессии.",
          diagnostic: {
            stage: "token",
            code: "network_connect",
            http_status: 0,
            request_id: "",
          },
        },
      }),
    );
    await page
      .getByRole("button", { name: "Проверить подключение", exact: true })
      .click();
    await expect(page.getByRole("alert")).toContainText(
      "Этап: получение сессии",
    );
    await expect(
      page.getByText(
        "WileyAI зарегистрирован в ChatGPT, но вход ещё не завершён",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByText("Код ошибки: network_connect", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Continue with ChatGPT", exact: true }),
    ).toBeEnabled();
    await expect(
      page.getByLabel("Ключ API", { exact: true }),
    ).not.toBeVisible();
  } finally {
    await app.close();
    clearFixtureCredentials(data);
  }
});

test("ChatGPT account completion selects an available model, persists it and shows plan usage once", async () => {
  const { app, page, before, data } = await launch();
  try {
    let connected = false;
    const id = await page.evaluate(async () => {
      const c = await window.wiley.connection();
      return (
        await (
          await fetch(c.url + "/chatgpt/status", {
            headers: { Authorization: "Bearer " + c.token },
          })
        ).json()
      ).connection_id;
    });
    await page.route("**/chatgpt/status", async (route) =>
      route.fulfill({
        json: {
          connection_id: id,
          connected,
          plan_enabled: connected,
          pending: false,
          email: connected ? "fixture@example.test" : "",
          error: "",
        },
      }),
    );
    await page.route("**/chatgpt/models", async (route) =>
      route.fulfill({
        json: {
          models: [
            { id: "account-model", name: "Модель аккаунта", size: 0 },
            { id: "second-model", name: "Другая доступная модель", size: 0 },
          ],
        },
      }),
    );
    await page.route("**/chatgpt/logout", async (route) => {
      connected = false;
      await route.continue();
    });
    connected = true;
    await page
      .getByRole("button", { name: "Continue with ChatGPT", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", {
        name: "Используется план ChatGPT",
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Понятно", exact: true }).click();
    await expect(
      page.getByLabel("Модель ChatGPT", { exact: true }),
    ).toHaveValue("account-model");
    await expect(
      page.getByText("Подключён ChatGPT: fixture@example.test", {
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Управлять лимитами ChatGPT", exact: true })
      .click();
    const urls: string[] = await app.evaluate(
      () => (globalThis as any).chatgptOpened,
    );
    expect(urls).toContain("https://chatgpt.com/settings/usage");
    const saved = await page.evaluate(async () => {
      const c = await window.wiley.connection();
      return (
        await fetch(c.url + "/settings", {
          headers: { Authorization: "Bearer " + c.token },
        })
      ).json();
    });
    expect(saved.provider).toBe("chatgpt");
    expect(saved.model).toBe("account-model");
    expect(saved.chatgpt_connection).toBe(id);
    expect(saved.tts_engine).toBe(before.tts_engine);
    expect(saved.stt_model).toBe(before.stt_model);
    await page.reload();
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: /Мозг/ }).click();
    await expect(
      page.getByLabel("Модель ChatGPT", { exact: true }),
    ).toHaveValue("account-model");
    await expect(
      page.getByRole("dialog", {
        name: "Используется план ChatGPT",
        exact: true,
      }),
    ).not.toBeVisible();
    await mkdir("local/review", { recursive: true });
    await page.screenshot({
      path: "local/review/chatgpt-account-settings.png",
    });
    await page
      .getByRole("button", { name: "Отключить ChatGPT", exact: true })
      .click();
    await expect(
      page.getByText("Аккаунт ChatGPT не подключён", { exact: true }),
    ).toBeVisible();
  } finally {
    await app.close();
    clearFixtureCredentials(data);
  }
});
