import { _electron as electron } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const [binary, profile, version] = process.argv.slice(2);
const work = resolve("local/release-qa");
if (!resolve(binary).startsWith(join(work, "nsis-installed") + "\\") ||
    resolve(profile) !== join(work, "windows-upgrade-profile")) throw new Error("Isolated upgrade test paths required");
const client = await electron.launch({
  executablePath: resolve(binary), cwd: resolve(profile),
  env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: resolve(profile) },
});
try {
  const page = await client.firstWindow();
  const state = await page.evaluate(async () => {
    const endpoint = await window.wiley.connection();
    const get = async (route) => {
      const response = await fetch(endpoint.url + route, { headers: { Authorization: "Bearer " + endpoint.token } });
      if (!response.ok) throw new Error(route + ": " + response.status);
      return response.json();
    };
    const [health, settings, history, memories] = await Promise.all([
      get("/health"), get("/settings"), get("/messages"), get("/memories"),
    ]);
    return { health, theme: settings.ui_theme, history, memories };
  });
  if (state.health.version !== version || state.theme !== "ice" ||
      !JSON.stringify(state.history).includes("WileyAI release QA message") ||
      !JSON.stringify(state.memories).includes("WileyAI release QA memory") ||
      (await readFile(join(profile, "models", "fixture.bin"))).toString("hex") !== "0c2c56") {
    throw new Error("Upgrade data or version changed unexpectedly");
  }
  console.log(`WileyAI ${version}: settings, SQLite chat and memory, and model marker verified`);
} finally {
  await client.close();
}
