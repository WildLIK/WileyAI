const test = require("node:test");
const assert = require("node:assert/strict");
const { startupPreferences } = require("../../desktop/startup.cjs");

test("startup is reversible, scoped to the installed executable and unavailable during tests/development", () => {
  const calls = [];
  let enabled = false;
  const app = {isPackaged: true, getLoginItemSettings: options => {calls.push(options); return {openAtLogin: enabled};},
    setLoginItemSettings: options => {calls.push(options); enabled = options.openAtLogin;}};
  const preferences = startupPreferences(app, {platform: "win32"});
  assert.equal(preferences.get().enabled, false);
  assert.equal(preferences.set(true).enabled, true);
  assert.equal(preferences.set(false).enabled, false);
  assert.ok(calls.every(options => options.path === process.execPath && options.args.join() === "--autostart"));
  assert.throws(() => preferences.set("yes"));
  const guarded = startupPreferences(app, {test: true, platform: "win32"});
  assert.equal(guarded.get().available, false);
  assert.throws(() => guarded.set(true));
});
