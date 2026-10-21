import { test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import {
  avatarTrayItems,
  installAvatarControls,
} from "../../desktop/avatar-controls.cjs";

test("click-through keeps control regions interactive and fails open after renderer loss or hide", () => {
  const handlers = new Map<string, (...args: any[]) => any>();
  let point = { x: -900, y: -650 },
    ignored = false,
    visible = true,
    sleeping = false,
    reads = 0;
  const window = Object.assign(new EventEmitter(), {
    webContents: new EventEmitter(),
    isDestroyed: () => false,
    isVisible: () => visible,
    isMinimized: () => false,
    getContentBounds: () => ({ x: -1000, y: -800, width: 480, height: 740 }),
    setIgnoreMouseEvents: (value: boolean) => {
      ignored = value;
    },
    hide: () => {
      visible = false;
      window.emit("hide");
    },
  });
  const controls = installAvatarControls({
    ipcMain: {
      handle: (name: string, handler: (...args: any[]) => any) =>
        handlers.set(name, handler),
    },
    BrowserWindow: { fromWebContents: () => window },
    windows: new Map([["avatar", window]]),
    screen: {
      getCursorScreenPoint: () => {
        reads++;
        return point;
      },
    },
    trusted: () => {},
    sendToWindow: () => {},
    changed: () => {},
    paused: () => sleeping,
  });
  controls.watch(window, "avatar");
  controls.setClickThrough(true);
  assert.equal(
    ignored,
    false,
    "Missing controls must not make the entire window unreachable",
  );
  const regions = [{ x: 0, y: 0, width: 480, height: 45 }];
  const publish = () =>
    handlers.get("avatar-control-regions")!(
      { sender: window.webContents },
      regions,
    );
  publish();
  assert.equal(
    ignored,
    true,
    "The model passes clicks through on negative-origin monitors",
  );
  point = { x: -900, y: -780 };
  publish();
  assert.equal(
    ignored,
    false,
    "The header is interactive without disabling the mode",
  );
  assert.equal(controls.state().clickThrough, true);
  point = { x: -900, y: -650 };
  publish();
  assert.equal(ignored, true);
  sleeping = true;
  const before = reads;
  publish();
  assert.equal(ignored, false);
  assert.equal(reads, before, "No cursor polling while suspended");
  sleeping = false;
  window.webContents.emit("render-process-gone");
  assert.equal(ignored, false);
  assert.equal(controls.state().clickThrough, false);
  controls.setClickThrough(true);
  publish();
  controls.hide();
  assert.deepEqual(controls.state(), { visible: false, clickThrough: false });
  assert.equal(ignored, false);
});

test("tray actions expose the real click-through state and hide only the avatar", () => {
  let visible = true,
    clickThrough = true,
    shown = false;
  const controls = {
    state: () => ({ visible, clickThrough }),
    setClickThrough: (value: boolean) => {
      clickThrough = value;
    },
    hide: () => {
      visible = false;
      clickThrough = false;
    },
  };
  let menu = avatarTrayItems(controls, () => {
    shown = true;
  });
  assert.equal(menu[1].checked, true);
  menu[1].click();
  assert.equal(clickThrough, false);
  menu = avatarTrayItems(controls, () => {
    shown = true;
  });
  assert.equal(menu[1].checked, false);
  menu[0].click();
  assert.equal(shown, true);
  menu[2].click();
  assert.equal(avatarTrayItems(controls, () => {})[1].enabled, false);
  assert.equal(visible, false);
});
