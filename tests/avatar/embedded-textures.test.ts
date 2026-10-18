import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "@playwright/test";

test("production CSP allows ImageBitmapLoader to fetch embedded GLB textures", async () => {
  const index = await readFile(
    new URL("../../index.html", import.meta.url),
    "utf8",
  );
  const policy = index.match(/content="(default-src[^\"]+)"/)?.[1];
  assert.ok(policy, "production CSP exists");
  const browser = await chromium.launch({
    executablePath:
      process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
    headless: true,
  });
  try {
    const page = await browser.newPage();
    await page.setContent(
      `<meta http-equiv="Content-Security-Policy" content="${policy}">`,
    );
    const size = await page.evaluate(async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 2;
      canvas.height = 2;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#00aaff";
      context.fillRect(0, 0, 2, 2);
      const png = await new Promise<Blob>((resolve) =>
        canvas.toBlob((blob) => resolve(blob!), "image/png"),
      );
      const url = URL.createObjectURL(png);
      try {
        const image = await createImageBitmap(await (await fetch(url)).blob());
        const result = [image.width, image.height];
        image.close();
        return result;
      } finally {
        URL.revokeObjectURL(url);
      }
    });
    assert.deepEqual(size, [2, 2]);
  } finally {
    await browser.close();
  }
});
