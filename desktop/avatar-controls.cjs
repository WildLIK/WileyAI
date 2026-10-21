function avatarTrayItems(controls, show) {
  const state = controls.state();
  return [
    { label: "Показать аватар", click: show },
    {
      label: "Пропуск кликов (Ctrl+Alt+A)",
      type: "checkbox",
      checked: state.clickThrough,
      enabled: state.visible,
      click: () => controls.setClickThrough(!controls.state().clickThrough),
    },
    {
      label: "Скрыть аватар",
      enabled: state.visible,
      click: () => controls.hide(),
    },
  ];
}

/** Click-through applies to the model, while its controls remain reachable. */
function installAvatarControls({
  ipcMain,
  BrowserWindow,
  windows,
  screen,
  trusted,
  sendToWindow,
  changed,
  paused,
}) {
  let clickThrough = false,
    ignored = false,
    regions = [];
  const avatar = () => {
    const window = windows.get("avatar");
    return window && !window.isDestroyed() ? window : null;
  };
  const state = () => ({
    visible: Boolean(avatar()?.isVisible()),
    clickThrough,
  });
  const report = () => {
    const window = avatar();
    if (window) sendToWindow(window, "avatar-controls", state());
    changed();
  };
  const ignore = (enabled) => {
    const window = avatar();
    if (!window || ignored === enabled) return;
    window.setIgnoreMouseEvents(enabled, { forward: true });
    ignored = enabled;
  };
  const refresh = () => {
    const window = avatar();
    if (
      !clickThrough ||
      !window ||
      !window.isVisible() ||
      window.isMinimized() ||
      paused() ||
      !regions.length
    ) {
      ignore(false);
      return;
    }
    const point = screen.getCursorScreenPoint(),
      bounds = window.getContentBounds();
    const x = point.x - bounds.x,
      y = point.y - bounds.y;
    ignore(
      !regions.some(
        (rect) =>
          x >= rect.x - 4 &&
          y >= rect.y - 4 &&
          x <= rect.x + rect.width + 4 &&
          y <= rect.y + rect.height + 4,
      ),
    );
  };
  const setClickThrough = (enabled) => {
    if (typeof enabled !== "boolean")
      throw new Error("Некорректный режим пропуска кликов");
    clickThrough = Boolean(enabled && avatar()?.isVisible());
    refresh();
    report();
    return state();
  };
  const closeTool = () => {
    const tool = windows.get("avatar-test");
    if (tool && !tool.isDestroyed()) tool.close();
  };
  const hide = () => {
    setClickThrough(false);
    closeTool();
    avatar()?.hide();
  };
  ipcMain.handle("avatar-controls-get", (event) => {
    trusted(event);
    return state();
  });
  ipcMain.handle("avatar-clickthrough", (event, enabled) => {
    trusted(event);
    if (BrowserWindow.fromWebContents(event.sender) !== avatar())
      throw new Error("Не окно персонажа");
    return setClickThrough(enabled);
  });
  ipcMain.handle("avatar-hide", (event) => {
    trusted(event);
    hide();
  });
  ipcMain.handle("avatar-control-regions", (event, value) => {
    trusted(event);
    if (BrowserWindow.fromWebContents(event.sender) !== avatar()) return;
    if (
      !Array.isArray(value) ||
      value.length > 32 ||
      value.some(
        (rect) =>
          !rect ||
          ![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) ||
          rect.width < 0 ||
          rect.height < 0,
      )
    )
      throw new Error("Некорректные области управления персонажем");
    regions = value.map(({ x, y, width, height }) => ({ x, y, width, height }));
    refresh();
  });
  setInterval(refresh, 60).unref();
  return {
    state,
    setClickThrough,
    hide,
    watch(window, view) {
      if (view !== "avatar") return;
      clickThrough = false;
      ignored = false;
      regions = [];
      window.on("show", report);
      window.on("hide", () => {
        setClickThrough(false);
        closeTool();
      });
      window.on("closed", () => {
        clickThrough = false;
        ignored = false;
        regions = [];
        changed();
      });
      const release = () => {
        regions = [];
        setClickThrough(false);
      };
      window.webContents.on("render-process-gone", release);
      window.webContents.on(
        "did-start-navigation",
        (_event, _url, _inPlace, main) => {
          if (main) release();
        },
      );
    },
  };
}
module.exports = { avatarTrayItems, installAvatarControls };
