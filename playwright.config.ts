import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/desktop",
  globalSetup: "./tests/desktop/global-setup.ts",
  timeout: 60000,
  workers: 1,
  use: { screenshot: "only-on-failure" },
  reporter: "list",
});
