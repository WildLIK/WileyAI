const test = require("node:test");
const assert = require("node:assert/strict");
const {
  liveContents,
  sendToWindow,
} = require("../../desktop/window-messages.cjs");

test("closing BrowserWindow with destroyed WebContents receives no IPC messages", () => {
  const closing = {
    isDestroyed: () => false,
    webContents: {
      isDestroyed: () => true,
      send: () => {
        throw new Error("Object has been destroyed");
      },
    },
  };
  assert.equal(liveContents(closing), null);
  assert.equal(sendToWindow(closing, "conversation-state", {}), false);
});

test("destroyed windows are not accessed; live windows still receive updates", () => {
  const destroyed = {
    isDestroyed: () => true,
    get webContents() {
      throw new Error("Window was destroyed");
    },
  };
  assert.equal(sendToWindow(destroyed, "stop-all"), false);
  const sent = [];
  const live = {
    isDestroyed: () => false,
    webContents: {
      isDestroyed: () => false,
      send: (...args) => sent.push(args),
    },
  };
  assert.equal(
    sendToWindow(live, "conversation-state", { active: false }),
    true,
  );
  assert.deepEqual(sent, [["conversation-state", { active: false }]]);
});
