import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openAvatarTest } from "./avatar-test-helper";

test("music and 15/30/60 FPS ignore UI/system reduced motion, respect avatar switches and pause while hidden", async () => {
  test.skip(
    !process.env.WILEYAI_VRM_TEST_PATH,
    "Requires the local VRM fixture",
  );
  test.setTimeout(100000);
  const data = await mkdtemp(join(tmpdir(), "wiley-music-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    await app.context().addInitScript(() => {
      const state = { active: true, streams: 0 };
      (window as unknown as { musicFixture: typeof state }).musicFixture =
        state;
      const original = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        if (!String(input).endsWith("/avatar/music"))
          return original(input, init);
        state.streams++;
        let timer: ReturnType<typeof setInterval>;
        let closed = false;
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            const close = () => {
              if (!closed) {
                closed = true;
                clearInterval(timer);
                state.streams--;
                controller.close();
              }
            };
            init?.signal?.addEventListener("abort", close, { once: true });
            timer = setInterval(() => {
              if (closed) return;
              const phase = performance.now() / 500;
              controller.enqueue(
                encoder.encode(
                  "data: " +
                    JSON.stringify({
                      type: "music",
                      active: state.active,
                      source: state.active ? "AIMP" : "",
                      level: state.active ? 0.6 : 0,
                      beat: state.active
                        ? Math.max(0, Math.cos(phase * Math.PI * 2))
                        : 0,
                      phase,
                      bpm: 120,
                      error: "",
                    }) +
                    "\n\n",
                ),
              );
            }, 50);
          },
          cancel() {
            if (!closed) {
              closed = true;
              clearInterval(timer);
              state.streams--;
            }
          },
        });
        return new Response(body, {
          headers: { "Content-Type": "text/event-stream" },
        });
      };
    });
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
          avatar_music: true,
          avatar_motion: true,
          avatar_fps: 60,
          ui_motion: "reduced",
          speak_answers: false,
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
    await avatar.emulateMedia({ reducedMotion: "reduce" });
    const errors: string[] = [];
    avatar.on("pageerror", (e) => errors.push(e.message));
    const stage = avatar.locator(".avatar-stage");
    await expect(stage).toHaveAttribute("data-ready", "true", {
      timeout: 20000,
    });
    await expect(stage).toHaveAttribute("data-dancing", "true");
    await expect(avatar.locator("html")).toHaveAttribute(
      "data-motion",
      "reduced",
    );
    expect(
      await avatar.evaluate(
        () => matchMedia("(prefers-reduced-motion: reduce)").matches,
      ),
    ).toBe(true);
    await expect(stage).toHaveAttribute("data-music-source", "AIMP");
    await expect(stage.locator(".avatar-caption")).toContainText(/Танец/);
    const geometry = await stage.evaluate((e) => ({
      canvas: e.querySelector("canvas")!.getBoundingClientRect().bottom,
      caption: e.querySelector(".avatar-caption")!.getBoundingClientRect().top,
      controls: e
        .querySelector(".avatar-view-controls")!
        .getBoundingClientRect().top,
      captionBottom: e.querySelector(".avatar-caption")!.getBoundingClientRect()
        .bottom,
    }));
    expect(geometry.canvas).toBeLessThanOrEqual(geometry.caption + 1);
    expect(geometry.captionBottom).toBeLessThan(geometry.controls);
    await mkdir("local/review", { recursive: true });
    await page
      .getByRole("button", { name: "⚙ Настройки", exact: true })
      .click();
    await page.getByRole("tab", { name: "Аватар", exact: true }).click();
    const rates: Record<string, number> = {};
    for (const fps of [15, 30, 60]) {
      await page
        .getByLabel("Частота кадров аватара", { exact: true })
        .selectOption(String(fps));
      await page
        .getByRole("button", { name: "Сохранить", exact: true })
        .click();
      await expect(stage).toHaveAttribute("data-target-fps", String(fps));
      await expect(stage).toHaveAttribute("data-dancing", "true");
      // Count actual WebGL renders, rather than trusting the requested limit.
      rates[fps] = await stage.evaluate(async (node) => {
        const start = performance.now();
        const frames = Number((node as HTMLElement).dataset.renderFrames);
        await new Promise((resolve) => setTimeout(resolve, 2100));
        return (
          ((Number((node as HTMLElement).dataset.renderFrames) - frames) *
            1000) /
          (performance.now() - start)
        );
      });
      expect(rates[fps]).toBeGreaterThan(fps * 0.75);
      expect(rates[fps]).toBeLessThan(fps * 1.1);
    }
    expect(rates[60]).toBeGreaterThan(rates[30] * 1.5);
    await stage
      .getByRole("button", { name: "Статистика 3D", exact: true })
      .click();
    await expect(stage.locator("output")).toContainText("предел 60");
    await writeFile(
      "local/review/avatar-fps-reduced.json",
      JSON.stringify(rates, null, 2),
    );
    for (const [side, x] of [
      ["left", -20000],
      ["right", 20000],
    ] as const) {
      await app.evaluate(({ screen }, x) => {
        screen.getCursorScreenPoint = () => ({ x, y: 400 });
      }, x);
      await expect(stage).toHaveAttribute(
        "data-gaze-x",
        side === "left" ? "-1.00" : "1.00",
      );
    }
    for (const name of [
      "Танцевать под звук плееров и браузера",
      "Дыхание, движения в покое и жесты",
    ]) {
      await page.getByLabel(name, { exact: true }).uncheck();
      await page
        .getByRole("button", { name: "Сохранить", exact: true })
        .click();
      await expect(stage).toHaveAttribute("data-dancing", "false");
      await expect(stage.locator(".avatar-music-status")).toContainText(
        "выключен",
      );
      expect(
        await avatar.evaluate(
          () =>
            (window as unknown as { musicFixture: { streams: number } })
              .musicFixture.streams,
        ),
      ).toBe(0);
      await page.getByLabel(name, { exact: true }).check();
      await page
        .getByRole("button", { name: "Сохранить", exact: true })
        .click();
      await expect(stage).toHaveAttribute("data-dancing", "true");
    }
    await page.getByRole("button", { name: "◈ Общение", exact: true }).click();
    for (let i = 0; i < 3; i++) {
      await avatar.waitForTimeout(1100);
      await stage.locator("canvas").screenshot({
        path: `local/review/avatar-dance-${i}.png`,
        omitBackground: true,
      });
    }
    await avatar.evaluate(() => {
      (
        window as unknown as { musicFixture: { active: boolean } }
      ).musicFixture.active = false;
    });
    await expect(stage).toHaveAttribute("data-dancing", "false");
    await avatar.evaluate(() => {
      (
        window as unknown as { musicFixture: { active: boolean } }
      ).musicFixture.active = true;
    });
    await expect(stage).toHaveAttribute("data-dancing", "true");
    await avatar.evaluate(() =>
      window.wiley.updateAvatar({
        phase: "speaking",
        emotion: "neutral",
        gesture: "none",
        cue: "music-test",
        voice: true,
        energy: 0,
      }),
    );
    await expect(stage).toHaveAttribute("data-pose", "explain");
    await expect(stage).toHaveAttribute("data-dancing", "false");
    await avatar.evaluate(() =>
      window.wiley.updateAvatar({
        phase: "idle",
        emotion: "neutral",
        gesture: "none",
        cue: "",
        voice: false,
        energy: 0,
      }),
    );
    await expect(stage).toHaveAttribute("data-dancing", "true");
    const tool = await openAvatarTest(app, page);
    // Opening controls alone must not silently replace automatic dancing with
    // a held neutral preview. Only an explicit pose button starts a test.
    await expect(stage).toHaveAttribute("data-testing", "false");
    await expect(stage).toHaveAttribute("data-dancing", "true");
    await expect(
      tool.getByRole("button", { name: "Авто", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      tool.getByRole("button", { name: "Нейтрально", exact: true }),
    ).toHaveAttribute("aria-pressed", "false");
    await tool.getByRole("button", { name: "Танец", exact: true }).click();
    await expect(stage).toHaveAttribute("data-demo", "Танец");
    await expect(stage).toHaveAttribute("data-pose", "dance");
    for (const [label, gesture] of [
      ["Танец 2", "dance2"],
      ["Танец 3", "dance3"],
    ]) {
      await tool.getByRole("button", { name: label, exact: true }).click();
      await expect(stage).toHaveAttribute("data-pose", gesture);
      await expect(stage.locator(".avatar-caption")).toContainText(label);
      await avatar.waitForTimeout(3100);
      await stage.screenshot({
        path: `local/review/avatar-${gesture}-reference.png`,
        omitBackground: true,
      });
    }
    await expect
      .poll(() =>
        avatar.evaluate(
          () =>
            (window as unknown as { musicFixture: { streams: number } })
              .musicFixture.streams,
        ),
      )
      .toBe(0);
    await expect(stage.locator(".avatar-music-status")).toContainText(
      "Ручной тест",
    );
    await stage.getByRole("button", { name: "Авто", exact: true }).click();
    await expect(stage).toHaveAttribute("data-demo", "");
    await expect(stage).toHaveAttribute("data-dancing", "true");
    await expect
      .poll(() =>
        avatar.evaluate(
          () =>
            (window as unknown as { musicFixture: { streams: number } })
              .musicFixture.streams,
        ),
      )
      .toBe(1);
    await avatar.evaluate(() => window.wiley.hideAvatar());
    await expect(stage).toHaveAttribute("data-render", "paused");
    await expect
      .poll(() =>
        avatar.evaluate(
          () =>
            (window as unknown as { musicFixture: { streams: number } })
              .musicFixture.streams,
        ),
      )
      .toBe(0);
    expect(errors).toEqual([]);
  } finally {
    await app.close();
  }
});
