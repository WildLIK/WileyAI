import {
  test,
  expect,
  _electron as electron,
  type Page,
} from "@playwright/test";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { openAvatarTest } from "./avatar-test-helper";

async function pixels(page: Page) {
  return page.locator(".avatar-stage canvas").evaluate(async (node) => {
    const canvas = node as HTMLCanvasElement,
      gl = canvas.getContext("webgl2")!;
    for (let attempt = 0; attempt < 20; attempt++) {
      await new Promise(requestAnimationFrame);
      const bytes = new Uint8Array(canvas.width * canvas.height * 4);
      gl.readPixels(
        0,
        0,
        canvas.width,
        canvas.height,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        bytes,
      );
      const sample: number[] = [];
      for (let y = 0; y < canvas.height; y += 4)
        for (let x = 0; x < canvas.width; x += 4) {
          const i = (y * canvas.width + x) * 4;
          sample.push(bytes[i], bytes[i + 1], bytes[i + 2], bytes[i + 3]);
        }
      if (sample.some((value) => value > 0)) return sample;
    }
    throw new Error("No rendered VRM pixels");
  });
}

test("VRM expressions: manual controls visibly deform every face, repeat gestures and leave the conversation untouched", async () => {
  test.skip(
    !process.env.WILEYAI_VRM_TEST_PATH,
    "Requires an embedded local VRM fixture",
  );
  test.setTimeout(90000);
  const data = await mkdtemp(join(tmpdir(), "wiley-avatar-expressions-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  await app.evaluate(() => {
    const errors: string[] = [];
    (
      globalThis as typeof globalThis & { avatarErrors: string[] }
    ).avatarErrors = errors;
    process.on("uncaughtException", (error) =>
      errors.push(error.stack || error.message),
    );
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
      const response = await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...settings,
          avatar_path: path,
          avatar_motion: false,
          avatar_gaze: false,
          avatar_expressions: false,
        }),
      });
      if (!response.ok) throw new Error("Fixture settings failed");
    }, process.env.WILEYAI_VRM_TEST_PATH!);
    await page.reload();
    const opened = app.waitForEvent("window");
    await page
      .getByRole("button", { name: "Показать аватара", exact: true })
      .click();
    const avatar = await opened;
    const errors: string[] = [];
    avatar.on("pageerror", (error) => errors.push(error.message));
    let commands = 0;
    avatar.on("request", (request) => {
      if (/\/(chat|voice\/synthesize)(?:\?|$)/.test(request.url())) commands++;
    });
    await avatar.setViewportSize({ width: 480, height: 850 });
    const stage = avatar.locator(".avatar-stage");
    await expect(stage).toHaveAttribute("data-ready", "true", {
      timeout: 20000,
    });
    const oldZoom = await stage.getAttribute("data-zoom");
    const oldHeight = (await stage.locator("canvas").boundingBox())!.height;
    await expect(
      avatar.getByRole("button", { name: /Тест|Проверить эмоции/ }),
    ).toHaveCount(0);
    const tool = await openAvatarTest(app, page);
    tool.on("pageerror", (error) => errors.push(error.message));
    const panel = tool.getByRole("region", {
      name: "Проверка эмоций и жестов",
      exact: true,
    });
    await expect(panel).toContainText("Костей крыльев: 6");
    await expect(stage).toHaveAttribute("data-testing", "false");
    await panel
      .getByRole("button", { name: "Нейтрально", exact: true })
      .click();
    await expect(stage).toHaveAttribute("data-testing", "true");
    expect((await stage.locator("canvas").boundingBox())!.height).toBe(
      oldHeight,
    );
    await expect(
      avatar.locator(".avatar-tests, .avatar-demo-remote"),
    ).toHaveCount(0);
    expect(
      await app.evaluate(({ BrowserWindow }) => {
        const a = BrowserWindow.getAllWindows()
          .find((w) => w.webContents.getURL().endsWith("view=avatar"))!
          .getBounds();
        const b = BrowserWindow.getAllWindows()
          .find((w) => w.webContents.getURL().endsWith("view=avatar-test"))!
          .getBounds();
        return (
          a.x + a.width <= b.x ||
          b.x + b.width <= a.x ||
          a.y + a.height <= b.y ||
          b.y + b.height <= a.y
        );
      }),
    ).toBe(true);
    // Face comparisons keep their deliberate close-up, independent of test launch.
    await stage
      .getByRole("button", { name: "Крупный план лица", exact: true })
      .click();
    const other = page.locator(".companion-panel .avatar-stage");
    await expect(other).toHaveAttribute("data-testing", "true");
    await mkdir("local/review", { recursive: true });
    await avatar.waitForTimeout(800);
    let baseline: number[] = [];
    const changed: Record<string, number> = {};
    for (const [name, emotion] of [
      ["Нейтрально", "neutral"],
      ["Радость", "happy"],
      ["Грусть", "sad"],
      ["Злость", "angry"],
      ["Удивление", "surprised"],
      ["Спокойствие", "relaxed"],
    ]) {
      await panel.getByRole("button", { name, exact: true }).click();
      await expect(stage).toHaveAttribute("data-emotion", emotion);
      await expect(other).toHaveAttribute("data-emotion", emotion);
      await avatar.waitForTimeout(650);
      const current = await pixels(avatar);
      if (emotion === "neutral") baseline = current;
      changed[emotion] = current.filter(
        (value, index) => Math.abs(value - baseline[index]) > 20,
      ).length;
      if (emotion !== "neutral")
        expect(
          changed[emotion],
          name + " must change rendered face pixels",
        ).toBeGreaterThan(20);
      await stage.locator("canvas").screenshot({
        path: `local/review/avatar-emotion-${emotion}.png`,
        omitBackground: true,
      });
    }
    await panel.getByRole("button", { name: "Помахать", exact: true }).click();
    await expect(stage).toHaveAttribute("data-demo", "Помахать");
    await expect(other).toHaveAttribute("data-demo", "Помахать");
    await expect(
      panel.getByRole("button", { name: "Помахать", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await panel.getByRole("tab", { name: "Позы феи", exact: true }).click();
    const greeting = panel.getByRole("button", {
      name: "Приветствие",
      exact: true,
    });
    await expect(greeting).toHaveAttribute("aria-pressed", "false");
    await greeting.click();
    await expect(greeting).toHaveAttribute("aria-pressed", "true");
    await expect(
      panel.getByRole("button", { name: "Помахать", exact: true }),
    ).toHaveAttribute("aria-pressed", "false");
    await expect(stage).toHaveAttribute("data-demo", "Приветствие");
    expect((await page.evaluate(() => window.wiley.avatarState())).phase).toBe(
      "idle",
    );
    await avatar.waitForTimeout(1200);
    await avatar.screenshot({
      path: "local/review/avatar-emotions-panel.png",
      omitBackground: true,
    });
    await panel.getByRole("button", { name: "Губы", exact: true }).click();
    await expect(stage).toHaveAttribute("data-mouth", "active");
    expect(commands).toBe(0);
    await panel.getByRole("button", { name: "Авто", exact: true }).click();
    await expect.poll(() => tool.isClosed()).toBe(true);
    await expect(stage).toHaveAttribute("data-zoom", "4.80");
    await expect(stage).toHaveAttribute("data-mouth", "closed");
    await expect(stage).toHaveAttribute("data-emotion", "neutral");
    await stage
      .getByRole("button", { name: "Крупный план лица", exact: true })
      .click();
    await expect(stage).toHaveAttribute("data-zoom", "4.80");
    await avatar.waitForTimeout(500);
    await stage.locator("canvas").screenshot({
      path: "local/review/avatar-face-closeup.png",
      omitBackground: true,
    });
    for (let i = 0; i < 2; i++)
      await stage
        .getByRole("button", { name: "Приблизить аватара", exact: true })
        .click();
    await expect(stage).toHaveAttribute("data-zoom", "6.00");
    await expect(
      stage.getByRole("button", { name: "Приблизить аватара", exact: true }),
    ).toBeDisabled();
    await expect(
      page.locator(".companion-panel .avatar-stage"),
    ).toHaveAttribute("data-testing", "false");
    expect(errors).toEqual([]);
    const toolAgain = await openAvatarTest(app, page);
    await toolAgain
      .getByRole("button", { name: "Нейтрально", exact: true })
      .click();
    await expect(other).toHaveAttribute("data-testing", "true");
    await toolAgain.close();
    await expect(other).toHaveAttribute("data-testing", "false");
    await expect(stage).toHaveAttribute("data-testing", "false");
    await stage
      .getByRole("button", { name: "Сбросить вид аватара", exact: true })
      .click();
    await expect(stage).toHaveAttribute("data-zoom", oldZoom!);
    expect(
      await app.evaluate(
        () =>
          (globalThis as typeof globalThis & { avatarErrors: string[] })
            .avatarErrors,
      ),
    ).toEqual([]);
    await writeFile(
      "local/review/avatar-expression-pixels.json",
      JSON.stringify(changed, null, 2),
    );
  } finally {
    await app.close();
  }
});
