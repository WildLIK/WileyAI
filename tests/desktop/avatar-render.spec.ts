import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { wav } from "../../src/voice/speech";

async function visiblePixels(page: Page) {
  return page.locator(".avatar-stage canvas").evaluate(async (node) => {
    const canvas = node as HTMLCanvasElement;
    const gl = canvas.getContext("webgl2")!;
    let best = 0;
    for (let frame = 0; frame < 8; frame++) {
      await new Promise(requestAnimationFrame);
      const pixels = new Uint8Array(canvas.width * canvas.height * 4);
      gl.readPixels(
        0,
        0,
        canvas.width,
        canvas.height,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        pixels,
      );
      let count = 0;
      for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 40) count++;
      best = Math.max(best, count);
    }
    return best;
  });
}

test("avatar remains rendered during cross-window speech, narrow resize and context recovery", async () => {
  test.skip(
    !process.env.WILEYAI_VRM_TEST_PATH,
    "Requires a local VRM fixture with embedded textures",
  );
  const data = await mkdtemp(join(tmpdir(), "wiley-avatar-render-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    await page.evaluate(async (path) => {
      const { url, token } = await window.wiley.connection();
      const headers = {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
      };
      const settings = await (
        await fetch(url + "/settings", { headers })
      ).json();
      await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...settings,
          avatar_path: path,
          speak_answers: true,
          tts_engine: "sapi",
        }),
      });
    }, process.env.WILEYAI_VRM_TEST_PATH!);
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Привет, я Уайли." }),
    ).toBeVisible();
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    await expect(avatar.locator(".avatar-stage canvas")).toBeVisible();
    await expect.poll(() => visiblePixels(avatar)).toBeGreaterThan(500);
    await expect(avatar.locator(".avatar-error")).toHaveCount(0);
    await avatar
      .locator("canvas")
      .evaluate((node) => node.setAttribute("data-original-canvas", "yes"));
    await page.route("**/voice/synthesize", (route) =>
      route.fulfill({
        contentType: "audio/wav",
        body: Buffer.from(wav(new Float32Array(16000 * 7), 16000)),
      }),
    );
    await page.route("**/chat", (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: [
          { type: "delta", text: "Проверочная фраза для озвучки." },
          {
            type: "done",
            message: {
              id: "test-voice",
              role: "assistant",
              content: "Проверочная фраза для озвучки.",
              created: new Date().toISOString(),
            },
          },
        ]
          .map((event) => "data: " + JSON.stringify(event) + "\n\n")
          .join(""),
      }),
    );
    await page
      .getByLabel("Сообщение", { exact: true })
      .fill("Проверка аватара");
    await page.getByRole("button", { name: "Отправить", exact: true }).click();
    await expect(
      avatar.getByText("Озвучка в другом окне", { exact: true }),
    ).toBeVisible();
    await avatar.setViewportSize({ width: 300, height: 420 });
    await expect(
      avatar.locator('canvas[data-original-canvas="yes"]'),
    ).toBeVisible();
    await expect.poll(() => visiblePixels(avatar)).toBeGreaterThan(100);
    await expect(avatar.locator(".avatar-error")).toHaveCount(0);
    await avatar.screenshot({
      path: "local/screenshots/avatar-speaking.png",
      omitBackground: true,
    });
    await expect(
      avatar.getByText("Озвучка в другом окне", { exact: true }),
    ).toHaveCount(0, { timeout: 12000 });
    await expect.poll(() => visiblePixels(avatar)).toBeGreaterThan(500);
    await avatar.locator("canvas").evaluate((node) => {
      const gl = (node as HTMLCanvasElement).getContext("webgl2")!;
      const extension = gl.getExtension("WEBGL_lose_context")!;
      extension.loseContext();
      setTimeout(() => extension.restoreContext(), 400);
    });
    await expect(
      avatar.getByText("Восстанавливаю 3D после сбоя видеодрайвера…"),
    ).toBeVisible();
    await expect(avatar.locator(".avatar-error")).toHaveCount(0);
    await expect.poll(() => visiblePixels(avatar)).toBeGreaterThan(500);
  } finally {
    await app.close();
  }
});
