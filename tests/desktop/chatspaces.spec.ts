import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { createServer } from "node:http";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("chats and projects: independent context, create/rename/move/delete, compact layout and saved panels", async () => {
  const prompts: { messages: { role: string; content: string }[] }[] = [];
  const model = createServer(async (req, res) => {
    if (req.method === "GET") {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ data: [{ id: "chat-space-test" }] }));
      return;
    }
    const body = [];
    for await (const chunk of req) body.push(chunk);
    prompts.push(JSON.parse(Buffer.concat(body).toString()));
    res.setHeader("Content-Type", "text/event-stream");
    res.end(
      'data: {"choices":[{"delta":{"content":"Ответ только текущему чату."}}]}\n\ndata: [DONE]\n\n',
    );
  });
  await new Promise<void>((resolve) => model.listen(0, "127.0.0.1", resolve));
  const address = model.address();
  if (!address || typeof address === "string") throw new Error("No model port");
  const data = await mkdtemp(join(tmpdir(), "wileyai-spaces-"));
  const launch = () =>
    electron.launch({
      args: ["."],
      env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
    });
  let app = await launch();
  const send = async (page: Page, text: string) => {
    const count = await page.locator(".message.assistant").count();
    await page.getByLabel("Сообщение", { exact: true }).fill(text);
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(page.locator(".message.assistant")).toHaveCount(count + 1);
    await expect(
      page.getByRole("button", { name: "Отправить", exact: true }),
    ).toBeVisible();
  };
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(async (base_url) => {
      const { url, token } = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      };
      const config = await (await fetch(url + "/settings", { headers })).json();
      await fetch(url + "/settings", {
        headers,
        method: "PUT",
        body: JSON.stringify({
          ...config,
          provider: "compatible",
          base_url,
          model: "chat-space-test",
        }),
      });
      const channel = new BroadcastChannel("wiley-ui");
      channel.postMessage({ type: "settings" });
      channel.close();
    }, `http://127.0.0.1:${address.port}`);
    await send(page, "Запомни: ОБЩИЙ-КОД-121");
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toHaveCount(0);
    await expect(page.locator(".conversation-banner")).toHaveCount(0);
    await expect(page.locator(".chat-toolbar")).toHaveCSS("flex-shrink", "0");
    const toolbar = await page.locator(".chat-toolbar").boundingBox();
    expect(toolbar!.height).toBeLessThan(100);
    await page
      .getByRole("button", { name: "＋ Новый чат", exact: true })
      .click();
    await expect(page.locator(".message")).toHaveCount(0);
    await send(page, "Личная тема второго чата");
    expect(prompts.at(-1)!.messages[0].content).toContain("ОБЩИЙ-КОД-121");
    expect(
      prompts.at(-1)!.messages.filter((item) => item.role !== "system"),
    ).toHaveLength(1);
    await page
      .getByRole("button", {
        name: "Управление чатом «Личная тема второго чата»",
      })
      .click();
    await page.getByLabel("Название чата").fill("Рабочие идеи");
    await page
      .getByRole("button", { name: "Сохранить изменения", exact: true })
      .click();
    await expect(page.locator(".chat-toolbar h1")).toHaveText("Рабочие идеи");
    await page.getByLabel("Сообщение", { exact: true }).fill("Личный черновик");
    await page.getByRole("button", { name: "＋ Проект", exact: true }).click();
    await page.getByLabel("Название проекта").fill("Изолированный проект");
    await page
      .getByRole("button", { name: "Создать проект", exact: true })
      .click();
    await expect(page.locator(".chat-toolbar small")).toHaveText(
      "Память проекта «Изолированный проект»",
    );
    await expect(page.locator(".message")).toHaveCount(0);
    await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue("");
    await send(page, "Что помнишь об этом проекте?");
    expect(JSON.stringify(prompts.at(-1))).not.toContain("ОБЩИЙ-КОД-121");
    expect(JSON.stringify(prompts.at(-1))).not.toContain(
      "Личная тема второго чата",
    );
    await send(page, "Запомни: ПРОЕКТ-КОД-747");
    await page.locator("input[type=file]").setInputFiles({
      name: "project.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("PRIVATE-PROJECT-DOCUMENT"),
    });
    await expect(
      page.getByRole("button", { name: "▤ project.txt", exact: true }),
    ).toBeVisible();
    let releaseChatLoad!: () => void;
    const chatLoadGate = new Promise<void>((resolve) => {
      releaseChatLoad = resolve;
    });
    await page.route("**/conversations", async (route) => {
      if (route.request().method() === "GET") await chatLoadGate;
      await route.continue();
    });
    await page
      .getByRole("button", {
        name: "Новый чат в проекте «Изолированный проект»",
      })
      .click();
    try {
      await expect(page.locator(".message")).toHaveCount(0);
      await expect(
        page.getByLabel("Сообщение", { exact: true }),
      ).toBeDisabled();
    } finally {
      releaseChatLoad();
    }
    await page.unrouteAll({ behavior: "wait" });
    await expect(
      page.getByRole("button", { name: "▤ project.txt", exact: true }),
    ).toHaveCount(0);
    await send(page, "Продолжим работу в другом чате");
    expect(prompts.at(-1)!.messages[0].content).toContain("ПРОЕКТ-КОД-747");
    expect(JSON.stringify(prompts.at(-1))).not.toContain("ОБЩИЙ-КОД-121");
    expect(JSON.stringify(prompts.at(-1))).not.toContain(
      "PRIVATE-PROJECT-DOCUMENT",
    );
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Черновик проекта");
    await page.getByRole("button", { name: "◎ Память" }).click();
    await expect(page.locator(".memory-entry")).toHaveCount(1);
    await expect(page.locator(".memory-content")).toHaveText("ПРОЕКТ-КОД-747");
    // Moving history to a project must not copy the general memory into it.
    await page
      .getByRole("button", { name: "Управление чатом «Рабочие идеи»" })
      .click();
    await page
      .getByLabel("Расположение чата")
      .selectOption({ label: "Изолированный проект" });
    await page
      .getByRole("button", { name: "Сохранить изменения", exact: true })
      .click();
    await page
      .getByRole("button", { name: "◈ Рабочие идеи", exact: true })
      .click();
    await expect(page.locator(".chat-toolbar small")).toContainText(
      "Изолированный проект",
    );
    await expect(page.locator(".message.user .message-text")).toHaveText(
      "Личная тема второго чата",
    );
    await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue(
      "Личный черновик",
    );
    await page
      .getByRole("button", {
        name: "◈ Продолжим работу в другом чате",
        exact: true,
      })
      .click();
    await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue(
      "Черновик проекта",
    );
    await page
      .getByRole("button", { name: "◈ Рабочие идеи", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Управление чатом «Рабочие идеи»" })
      .click();
    await page
      .getByRole("button", { name: "Удалить чат", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", { name: "Подтверждение удаления" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Удалить навсегда", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "◈ Рабочие идеи", exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", {
        name: "Управление проектом «Изолированный проект»",
      })
      .click();
    await page.getByLabel("Название проекта").fill("Переименованный проект");
    await page
      .getByRole("button", { name: "Сохранить изменения", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "Управление проектом «Переименованный проект»",
      }),
    ).toBeVisible();
    await page.screenshot({
      path: "local/screenshots/chatspaces.png",
      fullPage: true,
    });
    // Both panels stay in the document flow and can be hidden at minimum size.
    await app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0].setSize(900, 650);
    });
    const panel = await page.locator(".chat-panel").boundingBox();
    const companion = await page.locator(".companion-panel").boundingBox();
    expect(companion!.x).toBeGreaterThanOrEqual(panel!.x + panel!.width - 1);
    const composer = await page.locator(".composer").boundingBox();
    expect(composer!.y + composer!.height).toBeLessThanOrEqual(650);
    await page
      .getByRole("button", { name: "Свернуть левую панель", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Свернуть панель аватара", exact: true })
      .click();
    await expect(page.locator(".companion-panel")).toHaveCount(0);
    expect((await page.locator(".sidebar").boundingBox())!.width).toBeLessThan(
      70,
    );
    expect(
      (await page.locator(".chat-panel").boundingBox())!.width,
    ).toBeGreaterThan(800);
    await page.screenshot({
      path: "local/screenshots/chatspaces-collapsed.png",
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Развернуть левую панель", exact: true })
      .click();
    await page
      .getByRole("button", {
        name: "Управление проектом «Переименованный проект»",
      })
      .click();
    await page
      .getByRole("button", { name: "Удалить проект", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Удалить навсегда", exact: true })
      .click();
    await expect(page.locator(".project-group")).toHaveCount(0);
    await expect(page.getByLabel("Сообщение", { exact: true })).toHaveValue("");
    await page.getByRole("button", { name: "◎ Память" }).click();
    await expect(page.locator(".memory-content")).toHaveText("ОБЩИЙ-КОД-121");
    await page.getByRole("button", { name: "◈ Общение" }).click();
    await page
      .getByRole("button", { name: "Свернуть левую панель", exact: true })
      .click();
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
  try {
    app = await launch();
    const page = await app.firstWindow();
    await expect(
      page.getByRole("button", {
        name: "Развернуть левую панель",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", {
        name: "Развернуть панель аватара",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.locator(".companion-panel")).toHaveCount(0);
    await expect(page.locator(".message.user .message-text")).toHaveText(
      "Запомни: ОБЩИЙ-КОД-121",
    );
  } finally {
    await app.close();
    model.closeAllConnections();
    await new Promise<void>((resolve) => model.close(() => resolve()));
  }
});
