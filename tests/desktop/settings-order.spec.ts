import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("settings broadcasts keep the newest response when an older snapshot finishes first", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-settings-order-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  const held: (() => void)[] = [];
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("settings"));
    const second = await opened;
    await expect(
      second.getByRole("heading", { name: "Настройки ассистента" }),
    ).toBeVisible();
    await expect(second.locator("html")).toHaveAttribute("data-motion", "full");
    await second.route("**/settings", async (route) => {
      const response = await route.fetch();
      const snapshot = await response.json();
      await new Promise<void>((resolve) => held.push(resolve));
      await route.fulfill({ response, json: snapshot });
    });
    const broadcast = () =>
      page.evaluate(() => {
        const channel = new BroadcastChannel("wiley-ui");
        channel.postMessage({ type: "settings" });
        channel.close();
      });
    await broadcast();
    await expect.poll(() => held.length).toBe(1);
    await page.evaluate(async () => {
      const { url, token } = await window.wiley.connection();
      const response = await fetch(url + "/settings/appearance", {
        method: "PATCH",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ui_motion: "reduced" }),
      });
      if (!response.ok) throw new Error("Fixture appearance save failed");
    });
    await broadcast();
    await expect.poll(() => held.length).toBe(2);
    const first = second.waitForResponse("**/settings");
    held[0]();
    await (await first).finished();
    await second.evaluate(() => new Promise(requestAnimationFrame));
    held[1]();
    await expect(second.locator("html")).toHaveAttribute(
      "data-motion",
      "reduced",
    );
  } finally {
    for (const release of held) release();
    await app.close();
  }
});
