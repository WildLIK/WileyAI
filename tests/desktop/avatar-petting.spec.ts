import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

test("right-click strokes only the head, smiles and blushes without losing minimal-mode recovery", async () => {
  test.skip(!process.env.WILEYAI_VRM_TEST_PATH, "Requires a local VRM fixture");
  test.setTimeout(90000);
  const data = await mkdtemp(join(tmpdir(), "wiley-petting-"));
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
      const r = await fetch(url + "/settings", {
        method: "PUT",
        headers,
        body: JSON.stringify({
          ...settings,
          avatar_path: path,
          avatar_fps: 60,
          avatar_motion: true,
          avatar_expressions: true,
          avatar_music: false,
          avatar_gaze: false,
          speak_answers: false,
        }),
      });
      if (!r.ok) throw new Error("Settings failed");
    }, process.env.WILEYAI_VRM_TEST_PATH!);
    await page.reload();
    const opened = app.waitForEvent("window");
    await page.evaluate(() => window.wiley.showWindow("avatar"));
    const avatar = await opened;
    const errors: string[] = [];
    avatar.on("pageerror", (e) => errors.push(e.message));
    const stage = avatar.locator(".avatar-stage");
    await expect(stage).toHaveAttribute("data-ready", "true", {
      timeout: 20000,
    });
    await avatar
      .getByRole("button", { name: "Крупный план лица", exact: true })
      .click();
    await avatar
      .getByRole("button", { name: "Только фея", exact: true })
      .click();
    await expect(avatar.locator(".pet-window")).toHaveAttribute(
      "data-minimal",
      "true",
    );
    const canvas = stage.locator("canvas");
    await expect(stage).toHaveAttribute("data-petting", "false");
    // Empty canvas is not pettable, even though it is in the avatar window.
    await canvas.dispatchEvent("pointerdown", {
      button: 2,
      clientX: 2,
      clientY: 2,
    });
    await expect(stage).toHaveAttribute("data-petting", "false");
    await mkdir("local/review", { recursive: true });
    await canvas.screenshot({ path: "local/review/avatar-pet-neutral.png" });
    const touch = async () => {
      const box = (await canvas.boundingBox())!;
      const x = Number(await stage.getAttribute("data-head-x"));
      const y = Number(await stage.getAttribute("data-head-y"));
      await avatar.mouse.click(box.x + x, box.y + y, { button: "right" });
    };
    await touch();
    await expect(stage).toHaveAttribute("data-petting", "true");
    await expect(stage.locator(".avatar-caption")).toContainText(
      "Мне приятно, спасибо",
    );
    await expect(avatar.locator(".pet-window")).toHaveAttribute(
      "data-minimal",
      "true",
    );
    await expect
      .poll(async () => Number(await stage.getAttribute("data-smile")))
      .toBeGreaterThan(0.45);
    await expect
      .poll(async () => Number(await stage.getAttribute("data-blush")))
      .toBeGreaterThan(0.5);
    await canvas.screenshot({ path: "local/review/avatar-pet-smile.png" });
    const box = (await canvas.boundingBox())!;
    const hx = Number(await stage.getAttribute("data-head-x"));
    const hy = Number(await stage.getAttribute("data-head-y"));
    await avatar.mouse.move(box.x + hx, box.y + hy);
    await avatar.mouse.down({ button: "right" });
    const strokeBurstMs = await canvas.evaluate(
      (element, point) => {
        const began = performance.now();
        for (let i = 0; i < 120; i++) {
          element.dispatchEvent(
            new PointerEvent("pointermove", {
              buttons: 2,
              clientX: point.x + (i % 2 ? -8 : 8),
              clientY: point.y,
            }),
          );
        }
        return performance.now() - began;
      },
      { x: box.x + hx, y: box.y + hy },
    );
    // A continuous stroke must not synchronously skin/raycast every triangle.
    expect(strokeBurstMs).toBeLessThan(100);
    for (let i = 0; i < 7; i++) {
      await avatar.waitForTimeout(500);
      await avatar.mouse.move(box.x + hx + (i % 2 ? -12 : 12), box.y + hy);
      await expect(stage).toHaveAttribute("data-petting", "true");
    }
    // Finishing the stroke away from the head must not restore the panels.
    await avatar.mouse.move(box.x + 3, box.y + 3);
    await avatar.mouse.up({ button: "right" });
    await expect(avatar.locator(".pet-window")).toHaveAttribute(
      "data-minimal",
      "true",
    );
    await expect(stage).toHaveAttribute("data-petting", "false", {
      timeout: 6000,
    });
    await expect
      .poll(async () => Number(await stage.getAttribute("data-blush")))
      .toBeLessThan(0.02);
    // The head is reachable in click-through mode; native control regions
    // track its screen position, rather than intercepting the whole canvas.
    await avatar.evaluate(() => window.wiley.clickThrough(true));
    await expect
      .poll(() =>
        avatar.evaluate(() =>
          Boolean(
            document
              .querySelector(".avatar-head-region")
              ?.getBoundingClientRect().width,
          ),
        ),
      )
      .toBe(true);
    await touch();
    await expect(stage).toHaveAttribute("data-petting", "true");
    await avatar.evaluate(() => window.wiley.clickThrough(false));
    await canvas.click({ button: "right", position: { x: 3, y: 3 } });
    await expect(avatar.locator(".pet-window")).toHaveAttribute(
      "data-minimal",
      "false",
    );
    expect(errors).toEqual([]);
    await writeFile(
      "local/review/avatar-petting.json",
      JSON.stringify(
        {
          result: "PASS",
          model: process.env.WILEYAI_VRM_TEST_PATH,
          headOnly: true,
          smile: true,
          blush: true,
          strokeBurstMs,
          minimalRestored: true,
        },
        null,
        2,
      ),
    );
  } finally {
    await app.close();
  }
});
