import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("chat follows the bottom, preserves reading position and offers a scroll arrow", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-scroll-"));
  const app = await electron.launch({
    args: ["."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const messages = Array.from({ length: 40 }, (_, index) => ({
      id: "scroll-" + index,
      role: index % 2 ? "assistant" : "user",
      content:
        `Реплика ${index}. ` + "Содержимое длинного сообщения. ".repeat(25),
      created: new Date().toISOString(),
    }));
    await page.route("**/messages?*", (route) =>
      route.fulfill({ json: messages }),
    );
    await page.reload();
    const viewport = page.locator(".messages");
    const distance = () =>
      viewport.evaluate(
        (element) =>
          element.scrollHeight - element.clientHeight - element.scrollTop,
      );
    await expect.poll(distance).toBeLessThan(5);
    await viewport.evaluate((element) => {
      element.scrollTop = 100;
    });
    const arrow = page.getByRole("button", {
      name: "К последнему сообщению",
      exact: true,
    });
    await expect(arrow).toBeVisible();
    // Grow content as a streamed answer would: a resize must not steal the
    // reading position while the user is above the bottom.
    await viewport.locator(":scope > div").evaluate((element) => {
      const extra = document.createElement("p");
      extra.textContent = "Новый фрагмент. ".repeat(100);
      element.append(extra);
    });
    await expect
      .poll(() => viewport.evaluate((element) => element.scrollTop))
      .toBe(100);
    await arrow.click();
    await expect.poll(distance).toBeLessThan(5);
    await expect(arrow).toHaveCount(0);
    await viewport.locator(":scope > div").evaluate((element) => {
      const extra = document.createElement("p");
      extra.textContent = "Продолжение потока. ".repeat(100);
      element.append(extra);
    });
    await expect.poll(distance).toBeLessThan(5);
    await viewport.evaluate((element) => {
      element.scrollTop -= 600;
    });
    await expect(arrow).toBeVisible();
    await page.screenshot({
      path: "local/screenshots/chat-scroll.png",
      fullPage: true,
    });
  } finally {
    await app.close();
  }
});
