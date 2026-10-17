const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { APP_ID } = require("../../desktop/identity.cjs");
const root = resolve(__dirname, "../..");

test("installed notification identity matches the NSIS shortcut", () => {
  const config = readFileSync(resolve(root, "electron-builder.yml"), "utf8");
  assert.equal(config.match(/^appId: (.+)$/m)[1], APP_ID);
});

test("installer, Python metadata and update checker use the same version", () => {
  const version = JSON.parse(
    readFileSync(resolve(root, "package.json"), "utf8"),
  ).version;
  assert.equal(
    readFileSync(resolve(root, "core/version.py"), "utf8").match(
      /VERSION = "([^"]+)"/,
    )[1],
    version,
  );
  assert.equal(
    readFileSync(resolve(root, "pyproject.toml"), "utf8").match(
      /^version = "([^"]+)"/m,
    )[1],
    version,
  );
});
