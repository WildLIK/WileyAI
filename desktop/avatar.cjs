const idle = {
  phase: "idle",
  emotion: "neutral",
  gesture: "none",
  cue: "",
  voice: false,
  energy: 0,
};
const priorities = { idle: 0, listening: 1, thinking: 2, speaking: 3 };
function checkedSignal(value) {
  if (
    !value ||
    !Object.hasOwn(priorities, value.phase) ||
    !["neutral", "happy", "sad", "angry", "relaxed", "surprised"].includes(
      value.emotion,
    ) ||
    ![
      "none",
      "wave",
      "nod",
      "comfort",
      "joy",
      "cute",
      "explain",
      "think",
      "praise",
      "point",
      "listen",
      "thumbsup",
      "shy",
      "tired",
    ].includes(value.gesture) ||
    typeof value.cue !== "string" ||
    value.cue.length > 80 ||
    (value.voice !== undefined && typeof value.voice !== "boolean") ||
    (value.energy !== undefined &&
      (typeof value.energy !== "number" ||
        !Number.isFinite(value.energy) ||
        value.energy < 0 ||
        value.energy > 1))
  )
    throw new Error("Некорректное состояние персонажа");
  return {
    phase: value.phase,
    emotion: value.emotion,
    gesture: value.gesture,
    cue: value.cue,
    voice: Boolean(value.voice),
    energy: value.energy || 0,
  };
}

/** Bounded ephemeral presentation state, shared by all windows. No chat text. */
class AvatarSignals {
  constructor(changed = () => {}, clock = Date.now) {
    this.changed = changed;
    this.clock = clock;
    this.sources = new Map();
    this.value = idle;
    this.revision = 0;
  }
  update(sender, value) {
    this.sources.set(sender, {
      signal: checkedSignal(value),
      at: this.clock(),
    });
    this.refresh();
  }
  release(sender) {
    this.sources.delete(sender);
    this.refresh();
  }
  clear() {
    this.sources.clear();
    this.refresh();
  }
  state() {
    this.refresh();
    return { ...this.value, revision: this.revision };
  }
  refresh() {
    const now = this.clock();
    for (const [sender, value] of this.sources)
      if (now - value.at > 15000) this.sources.delete(sender);
    const values = [...this.sources.values()].filter(
      (row) =>
        row.signal.phase !== "idle" || row.signal.cue || row.signal.energy,
    );
    values.sort(
      (a, b) =>
        priorities[b.signal.phase] - priorities[a.signal.phase] || b.at - a.at,
    );
    const value = {
      ...(values[0]?.signal || idle),
      voice: values.some((row) => row.signal.voice),
      energy: Math.max(0, ...values.map((row) => row.signal.energy || 0)),
    };
    if (JSON.stringify(value) === JSON.stringify(this.value)) return;
    this.value = value;
    this.revision++;
    this.changed({ ...value, revision: this.revision });
  }
}

/** A preview lease never overwrites real conversation/speech state. */
class AvatarDemos {
  constructor(changed = () => {}, clock = Date.now) {
    this.changed = changed;
    this.clock = clock;
    this.demo = null;
    this.sender = null;
    this.revision = 0;
  }
  state(sender) {
    this.refresh();
    return {
      demo: this.demo,
      owner: this.demo !== null && sender === this.sender,
      revision: this.revision,
    };
  }
  update(sender, value, renew = false) {
    if (renew && sender !== this.sender) return;
    if (value === null) return this.clear();
    if (
      !value ||
      typeof value.strength !== "number" ||
      !Number.isFinite(value.strength) ||
      value.strength < 0 ||
      value.strength > 1 ||
      typeof value.still !== "boolean" ||
      typeof value.label !== "string" ||
      value.label.length > 40
    )
      throw new Error("Некорректная проверка персонажа");
    const demo = {
      signal: { ...checkedSignal(value.signal), voice: false },
      strength: value.strength,
      still: value.still,
      label: value.label,
    };
    const changed =
      this.sender !== sender ||
      JSON.stringify(this.demo) !== JSON.stringify(demo);
    this.sender = sender;
    this.demo = demo;
    this.at = this.clock();
    if (changed) {
      this.revision++;
      this.changed();
    }
  }
  clear() {
    if (!this.demo) return;
    this.demo = null;
    this.sender = null;
    this.revision++;
    this.changed();
  }
  release(sender) {
    if (sender === this.sender) this.clear();
  }
  refresh() {
    if (this.demo && this.clock() - this.at > 15000) this.clear();
  }
}

/** Work areas and BrowserWindow bounds are both DIP, including negative origins. */
function fitWindow(bounds, area) {
  const width = Math.min(bounds.width, area.width),
    height = Math.min(bounds.height, area.height);
  return {
    width,
    height,
    x: Math.round(
      Math.min(Math.max(bounds.x, area.x), area.x + area.width - width),
    ),
    y: Math.round(
      Math.min(Math.max(bounds.y, area.y), area.y + area.height - height),
    ),
  };
}
function nextDisplayBounds(bounds, from, to) {
  const x = (bounds.x - from.x) / Math.max(1, from.width - bounds.width);
  const y = (bounds.y - from.y) / Math.max(1, from.height - bounds.height);
  return fitWindow(
    {
      ...bounds,
      x: to.x + x * Math.max(0, to.width - bounds.width),
      y: to.y + y * Math.max(0, to.height - bounds.height),
    },
    to,
  );
}

function installAvatar({
  ipcMain,
  BrowserWindow,
  windows,
  trusted,
  sendToWindow,
  screen,
  powerMonitor,
  activity,
  stop,
}) {
  let sleeping = false,
    locked = false;
  const pointerWindows = new Map();
  const capabilities = new Map();
  const available = () => [...capabilities.values()].at(-1) || null;
  const reportCapabilities = () => {
    const tool = windows.get("avatar-test");
    if (tool) sendToWindow(tool, "avatar-capabilities", available());
  };
  const signals = new AvatarSignals((value) => {
    for (const window of windows.values())
      sendToWindow(window, "avatar-state", value);
  });
  const demos = new AvatarDemos(() => {
    for (const window of windows.values())
      if (!window.isDestroyed() && !window.webContents.isDestroyed())
        sendToWindow(window, "avatar-demo", demos.state(window.webContents.id));
  });
  const report = () => {
    for (const window of windows.values()) activity(window);
  };
  const keepVisible = (attempt = 0) => {
    const window = windows.get("avatar");
    if (!window || window.isDestroyed()) return;
    const bounds = window.getBounds();
    const raw = screen.getDisplayMatching(bounds).workArea;
    // Leave two DIP for Windows' fractional-DPI rounding at display edges.
    const area = {
      x: raw.x + 2,
      y: raw.y + 2,
      width: Math.max(1, raw.width - 4),
      height: Math.max(1, raw.height - 4),
    };
    const fitted = fitWindow(bounds, area);
    if (Object.keys(fitted).some((key) => fitted[key] !== bounds[key])) {
      window.setMinimumSize(
        Math.min(300, fitted.width),
        Math.min(420, fitted.height),
      );
      window.setBounds(fitted);
      // Moving across monitors can change the native frame size asynchronously.
      if (attempt < 2) setTimeout(() => keepVisible(attempt + 1), 100).unref();
    }
  };
  ipcMain.handle("avatar-state-get", (event) => {
    trusted(event);
    return signals.state();
  });
  ipcMain.handle("avatar-state-update", (event, value) => {
    trusted(event);
    if (sleeping || locked) return;
    signals.update(event.sender.id, value);
  });
  ipcMain.handle("avatar-demo-get", (event) => {
    trusted(event);
    return demos.state(event.sender.id);
  });
  ipcMain.handle("avatar-demo-update", (event, value, renew) => {
    trusted(event);
    if (!sleeping && !locked)
      demos.update(event.sender.id, value, Boolean(renew));
    return demos.state(event.sender.id);
  });
  ipcMain.handle("avatar-demo-release", (event) => {
    trusted(event);
    demos.release(event.sender.id);
  });
  ipcMain.handle("avatar-test-close", (event) => {
    trusted(event);
    const window = BrowserWindow.fromWebContents(event.sender);
    if (window !== windows.get("avatar-test")) return;
    demos.release(event.sender.id);
    window.close();
  });
  ipcMain.handle("avatar-capabilities-get", (event) => {
    trusted(event);
    return available();
  });
  ipcMain.handle("avatar-capabilities-update", (event, value) => {
    trusted(event);
    if (value === null) capabilities.delete(event.sender.id);
    else {
      if (
        !value ||
        !Array.isArray(value.expressions) ||
        value.expressions.length > 20 ||
        !value.expressions.every(
          (name) => typeof name === "string" && name.length < 40,
        ) ||
        !Number.isInteger(value.wings) ||
        value.wings < 0 ||
        value.wings > 1000 ||
        typeof value.gestures !== "boolean"
      )
        throw new Error("Некорректные возможности VRM");
      capabilities.delete(event.sender.id);
      capabilities.set(event.sender.id, {
        expressions: value.expressions,
        wings: value.wings,
        gestures: value.gestures,
      });
    }
    reportCapabilities();
  });
  ipcMain.handle("avatar-pointer-watch", (event, enabled) => {
    trusted(event);
    if (typeof enabled !== "boolean")
      throw new Error("Некорректное слежение за указателем");
    if (enabled)
      pointerWindows.set(
        event.sender.id,
        BrowserWindow.fromWebContents(event.sender),
      );
    else pointerWindows.delete(event.sender.id);
  });
  setInterval(() => {
    if (sleeping || locked || !pointerWindows.size) return;
    let point;
    for (const [id, window] of pointerWindows) {
      if (!window || window.isDestroyed() || window.webContents.isDestroyed()) {
        pointerWindows.delete(id);
        continue;
      }
      if (!window.isVisible() || window.isMinimized()) continue;
      point ||= screen.getCursorScreenPoint();
      const bounds = window.getContentBounds();
      sendToWindow(window, "avatar-pointer", {
        x: point.x - bounds.x,
        y: point.y - bounds.y,
      });
    }
  }, 100).unref();
  ipcMain.handle("avatar-next-display", (event) => {
    trusted(event);
    const window = BrowserWindow.fromWebContents(event.sender);
    if (window !== windows.get("avatar")) return;
    const displays = screen.getAllDisplays();
    const current = screen.getDisplayMatching(window.getBounds());
    const next =
      displays[
        (displays.findIndex((display) => display.id === current.id) + 1) %
          displays.length
      ];
    window.setBounds(
      nextDisplayBounds(window.getBounds(), current.workArea, next.workArea),
    );
    setTimeout(() => keepVisible(), 100).unref();
    activity(window);
  });
  const pause = () => {
    signals.clear();
    demos.clear();
    stop();
    report();
  };
  powerMonitor.on("suspend", () => {
    sleeping = true;
    pause();
  });
  powerMonitor.on("resume", () => {
    sleeping = false;
    keepVisible();
    report();
  });
  powerMonitor.on("lock-screen", () => {
    locked = true;
    pause();
  });
  powerMonitor.on("unlock-screen", () => {
    locked = false;
    keepVisible();
    report();
  });
  for (const event of [
    "display-added",
    "display-removed",
    "display-metrics-changed",
  ])
    screen.on(event, () => {
      keepVisible();
      report();
    });
  setInterval(() => {
    signals.refresh();
    demos.refresh();
  }, 2000).unref();
  return {
    get paused() {
      return sleeping || locked;
    },
    watch(window) {
      const id = window.webContents.id;
      const release = () => {
        signals.release(id);
        demos.release(id);
        pointerWindows.delete(id);
        capabilities.delete(id);
        reportCapabilities();
      };
      window.on("hide", () => {
        if (
          window === windows.get("avatar-test") ||
          window === windows.get("avatar")
        )
          demos.clear();
      });
      window.on("closed", release);
      window.webContents.on("render-process-gone", release);
      window.webContents.on(
        "did-start-navigation",
        (_event, _url, _inPlace, main) => {
          if (main) release();
        },
      );
      window.on("moved", () => activity(window));
      window.once("ready-to-show", keepVisible);
    },
  };
}
module.exports = {
  AvatarSignals,
  AvatarDemos,
  fitWindow,
  nextDisplayBounds,
  installAvatar,
};
