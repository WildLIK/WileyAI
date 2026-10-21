const fs = require("node:fs");
const path = require("node:path");
const { fitWindow } = require("./avatar.cjs");

const defaultSize = { width: 480, height: 740 };
const sameBounds = (a, b) =>
  ["x", "y", "width", "height"].every((key) => a[key] === b[key]);
function workArea(screen, bounds) {
  const area = screen.getDisplayMatching(bounds).workArea;
  return {
    x: area.x + 2,
    y: area.y + 2,
    width: area.width - 4,
    height: area.height - 4,
  };
}

/** Place the controls alongside the model, shifting the pair within the display. */
function besideAvatar(bounds, area, size = { width: 340, height: 540 }) {
  let avatar = fitWindow(bounds, area);
  const tool = {
    width: Math.min(size.width, area.width),
    height: Math.min(size.height, area.height),
  };
  const gap = 12;
  if (avatar.width + tool.width + gap <= area.width) {
    const right = avatar.x + avatar.width + gap;
    if (right + tool.width <= area.x + area.width)
      return {
        avatar,
        tool: fitWindow({ ...tool, x: right, y: avatar.y }, area),
      };
    if (avatar.x - gap - tool.width >= area.x)
      return {
        avatar,
        tool: fitWindow(
          { ...tool, x: avatar.x - gap - tool.width, y: avatar.y },
          area,
        ),
      };
    avatar = {
      ...avatar,
      x: area.x + area.width - avatar.width - tool.width - gap,
    };
    return {
      avatar,
      tool: fitWindow(
        { ...tool, x: avatar.x + avatar.width + gap, y: avatar.y },
        area,
      ),
    };
  }
  // On narrow screens, share the width rather than stack one window over the fairy.
  const toolWidth = Math.min(tool.width, Math.floor((area.width - gap) / 2));
  avatar = fitWindow(
    { ...avatar, width: area.width - toolWidth - gap, x: area.x },
    area,
  );
  return {
    avatar,
    tool: fitWindow(
      {
        ...tool,
        width: toolWidth,
        x: avatar.x + avatar.width + gap,
        y: avatar.y,
      },
      area,
    ),
  };
}

function installAvatarLayout({
  ipcMain,
  BrowserWindow,
  screen,
  windows,
  trusted,
  sendToWindow,
  dataRoot,
}) {
  const file = path.join(dataRoot, "avatar-window.json");
  let saved;
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"));
    if (
      ["x", "y", "width", "height"].every((key) =>
        Number.isFinite(value[key]),
      ) &&
      value.width >= 300 &&
      value.height >= 420
    )
      saved = value;
  } catch {
    /* First run or an invalid preference uses the default size. */
  }
  let saving,
    arranging = false;
  const avatarWindow = () => windows.get("avatar");
  const sizeOf = (window) => {
    const { width, height } = window.getBounds();
    return { width, height };
  };
  const persist = () => {
    clearTimeout(saving);
    saving = setTimeout(() => {
      if (!saved) return;
      try {
        fs.mkdirSync(dataRoot, { recursive: true });
        fs.writeFileSync(file + ".tmp", JSON.stringify(saved));
        fs.renameSync(file + ".tmp", file);
      } catch {
        /* A read-only profile must not break window controls. */
      }
    }, 150);
    saving.unref();
  };
  const applyBounds = (window, bounds) => {
    window.setMinimumSize(
      Math.min(300, bounds.width),
      Math.min(420, bounds.height),
    );
    if (!sameBounds(window.getBounds(), bounds)) window.setBounds(bounds);
  };
  const arrange = () => {
    const avatar = avatarWindow(),
      tool = windows.get("avatar-test");
    if (
      arranging ||
      !avatar ||
      avatar.isDestroyed() ||
      !tool ||
      tool.isDestroyed()
    )
      return;
    arranging = true;
    try {
      const layout = besideAvatar(
        avatar.getBounds(),
        workArea(screen, avatar.getBounds()),
        sizeOf(tool),
      );
      applyBounds(avatar, layout.avatar);
      applyBounds(tool, layout.tool);
    } finally {
      arranging = false;
    }
  };
  ipcMain.handle("avatar-size-get", (event) => {
    trusted(event);
    const window = avatarWindow();
    return window && !window.isDestroyed() ? sizeOf(window) : defaultSize;
  });
  ipcMain.handle("avatar-size-set", (event, size) => {
    trusted(event);
    const window = avatarWindow();
    if (
      !window ||
      window.isDestroyed() ||
      BrowserWindow.fromWebContents(event.sender) !== window
    )
      throw new Error("Размер можно менять только в окне персонажа");
    const current = sizeOf(window);
    if (
      size &&
      Number.isFinite(size.scale) &&
      size.scale >= 0.5 &&
      size.scale <= 2
    )
      size = {
        width: current.width * size.scale,
        height: current.height * size.scale,
      };
    else if (
      size &&
      Number.isFinite(size.deltaWidth) &&
      Number.isFinite(size.deltaHeight)
    )
      size = {
        width: current.width + size.deltaWidth,
        height: current.height + size.deltaHeight,
      };
    if (!size || !Number.isFinite(size.width) || !Number.isFinite(size.height))
      throw new Error("Некорректный размер окна");
    applyBounds(
      window,
      fitWindow(
        {
          ...window.getBounds(),
          width: Math.max(300, Math.round(size.width)),
          height: Math.max(420, Math.round(size.height)),
        },
        workArea(screen, window.getBounds()),
      ),
    );
    arrange();
    return sizeOf(window);
  });
  return {
    initial() {
      return saved ? fitWindow(saved, workArea(screen, saved)) : defaultSize;
    },
    arrange,
    watch(window, view) {
      if (view !== "avatar") return;
      const restoring = saved ? { ...saved } : null;
      const changed = () => {
        if (window.isDestroyed()) return;
        saved = window.getBounds();
        persist();
        sendToWindow(window, "avatar-size", sizeOf(window));
        arrange();
      };
      window.on("resize", changed);
      window.on("moved", changed);
      window.once("show", () => {
        // Windows adds its invisible resize frame during creation. Apply the
        // measured saved bounds once that frame exists, before DIP rounding.
        if (restoring)
          applyBounds(
            window,
            fitWindow(restoring, workArea(screen, restoring)),
          );
        changed();
      });
    },
  };
}
module.exports = { besideAvatar, installAvatarLayout };
