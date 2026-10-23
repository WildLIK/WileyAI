import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { chromium } from "@playwright/test";
import ts from "typescript";
const root = resolve("."),
  model = process.env.WILEYAI_VRM_TEST_PATH;
if (!model)
  throw Error(
    "Set WILEYAI_VRM_TEST_PATH to a VRM with skirtRaiseLeft and skirtRaiseRight expressions",
  );
await mkdir(resolve(root, "local/review"), { recursive: true });
const html = `<html><body style="margin:0"><script type="importmap">{"imports":{"three":"/deps/three/build/three.module.js","three/":"/deps/three/","@pixiv/three-vrm":"/deps/@pixiv/three-vrm/lib/three-vrm.module.js"}}</script><script type="module" src="/viewer.js"></script></body></html>`;
const server = createServer(async (req, res) => {
  try {
    const p = new URL(req.url, "http://local").pathname;
    let file;
    if (p === "/") {
      res.setHeader("Content-Type", "text/html");
      res.end(html);
      return;
    }
    if (p === "/model") file = model;
    else if (p === "/viewer.js")
      file = resolve(root, "tests/desktop/fixtures/avatar-cloth-viewer.js");
    else if (p.startsWith("/src/")) {
      file = resolve(root, p.slice(1) + (p.endsWith(".ts") ? "" : ".ts"));
      if (
        !file.startsWith(resolve(root, "src") + "/") &&
        !file.startsWith(resolve(root, "src") + "\\")
      )
        throw Error("path");
      res.setHeader("Content-Type", "text/javascript");
      res.end(
        ts.transpileModule(await readFile(file, "utf8"), {
          compilerOptions: { target: 99, module: 99 },
        }).outputText,
      );
      return;
    } else if (p.startsWith("/deps/"))
      file = resolve(root, "node_modules", p.slice(6));
    else throw Error("route");
    res.setHeader(
      "Content-Type",
      extname(file) === ".js" ? "text/javascript" : "application/octet-stream",
    );
    res.end(await readFile(file));
  } catch (e) {
    res.statusCode = 500;
    res.end(String(e));
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 700, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("http://127.0.0.1:" + server.address().port);
  await page.waitForFunction(() => window.ready, { timeout: 30000 });
  const report = [];
  for (const [name, angle, detail, label, motionEnabled = true] of [
    ["none", 0, true, "hair"],
    ["none", Math.PI / 2, true, "ear-profile"],
    ["none", 0, false, "front"],
    ["none", Math.PI, false, "back"],
    ["none", 0, false, "static", false],
    ["shy", 0, false, "shy"],
    ["shy", Math.PI / 2, false, "shy-side"],
    ["listen", 0, false, "listen"],
    ["praise", 0, false, "praise"],
    ["dance2", 0, false, "dance2"],
    ["think", 0, false, "think"],
    ["joy", Math.PI / 2, "torso", "torso-side"],
    ["joy", -Math.PI / 3, "torso", "torso-three-quarter"],
    ["none", Math.PI / 2, "torso", "torso-idle-side"],
    ["praise", 0, "torso", "shoulders-raised"],
    ["dance2", -0.8, "torso", "shoulders-turn"],
    ["none", 0, "torso", "hands-and-shoulders"],
    ["none", -Math.PI / 4, "torso", "crossed-arms-three-quarter"],
    ["none", 0, "skirt", "waist-seam"],
    ["shy", -0.35, "underneath", "skirt-underneath"],
  ]) {
    report.push(
      await page.evaluate(
        ([n, a, d, m]) => window.pose(n, a, d, m),
        [name, angle, detail, motionEnabled],
      ),
    );
    await page.screenshot({
      path: resolve(root, "local/review/avatar-cloth-" + label + ".png"),
    });
  }
  const sweep = await page.evaluate(() => window.sweep());
  await writeFile(
    "local/review/avatar-cloth-report.json",
    JSON.stringify({ errors, model, report, sweep }, null, 2),
  );
  console.log(JSON.stringify({ errors, sweep }));
  if (errors.length) throw Error(errors.join("\n"));
  if (!report.some((r) => r.withoutCloth.inside > 0))
    throw Error("Control condition did not reproduce the original clipping");
  if (sweep.failures.length) throw Error("Cloth enters thigh capsules");
} finally {
  await browser.close();
  await new Promise((r) => server.close(r));
}
