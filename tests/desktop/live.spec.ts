import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

test("live: local model answers using an uploaded document and renders a VRM", async () => {
  test.skip(
    process.env.WILEYAI_LIVE_TESTS !== "1",
    "Requires a locally installed Ollama model and optional VRM fixture",
  );
  const data = await mkdtemp(join(tmpdir(), "wileyai-live-"));
  const app = await electron.launch({
    args: ["."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page
      .locator("input[type=file]")
      .setInputFiles({
        name: "контрольный-документ.txt",
        mimeType: "text/plain",
        buffer: Buffer.from(
          "Название проекта: WileyAI. Контрольный код проекта: КЕДР-42. Дата выпуска ещё не назначена.",
          "utf8",
        ),
      });
    await expect(
      page.getByRole("button", { name: "▤ контрольный-документ.txt" }),
    ).toBeVisible();
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill(
        "Какой контрольный код указан в документе? Ответь кратко и укажи имя источника.",
      );
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(
      page.locator(".message.assistant .message-text").last(),
    ).toContainText("КЕДР-42", { timeout: 90000 });
    await expect(
      page.getByRole("button", { name: "Отправить", exact: true }),
    ).toBeVisible({ timeout: 90000 });
    if (process.env.WILEYAI_VRM_TEST_PATH) {
      await page.evaluate(async (path) => {
        const connection = await window.wiley.connection();
        const headers = {
          Authorization: "Bearer " + connection.token,
          "Content-Type": "application/json",
        };
        const config = await (
          await fetch(connection.url + "/settings", { headers })
        ).json();
        await fetch(connection.url + "/settings", {
          method: "PUT",
          headers,
          body: JSON.stringify({ ...config, avatar_path: path }),
        });
        const channel = new BroadcastChannel("wiley-ui");
        channel.postMessage({ type: "settings" });
        channel.close();
      }, resolve(process.env.WILEYAI_VRM_TEST_PATH));
      await expect(page.locator(".avatar-stage canvas")).toBeVisible({
        timeout: 30000,
      });
      await expect(page.locator(".avatar-error")).toHaveCount(0);
      // Allow the first textured frame and shader compilation to complete.
      await page.waitForTimeout(3500);
    }
    await page.screenshot({
      path: "local/screenshots/live-chat.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
