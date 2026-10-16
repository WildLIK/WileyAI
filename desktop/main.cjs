const {
  app,
  BrowserWindow,
  ipcMain,
  dialog,
  protocol,
  net,
  Tray,
  Menu,
  nativeImage,
  globalShortcut,
  session,
  Notification,
} = require("electron");
const { spawn } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { ConversationLease } = require("./conversation.cjs");
const { liveContents, sendToWindow } = require("./window-messages.cjs");
const { installBackups } = require("./backups.cjs");
const { createNotificationDelivery } = require("./notifications.cjs");

const root = path.resolve(__dirname, "..");
const dev = process.env.WILEYAI_DEV === "1";
const test = process.env.WILEYAI_TEST === "1";
if (test && process.env.WILEYAI_DATA_DIR)
  app.setPath("userData", path.join(process.env.WILEYAI_DATA_DIR, "electron"));
const windows = new Map();
let core;
let connection;
let tray;
let quitting = false;
let ollamaProcess;
let notificationTimer;
let backups;
const conversation = new ConversationLease(() => {
  if (quitting) return;
  for (const window of windows.values()) {
    const contents = liveContents(window);
    if (contents)
      contents.send("conversation-state", conversation.state(contents.id));
  }
  if (tray && !tray.isDestroyed())
    tray.setToolTip(
      conversation.lease ? "WileyAI · разговор включён" : "WileyAI",
    );
});

const deliverNotifications = createNotificationDelivery({
  connection: () => connection,
  enabled: () => !backups?.restoring && !quitting,
  display: (item) => {
    try {
      if (Notification.isSupported()) {
        const notification = new Notification({
          title:
            item.kind === "calendar"
              ? "WileyAI · Встреча"
              : "WileyAI · Напоминание",
          body: item.title,
          icon: path.join(__dirname, "icon.png"),
        });
        notification.on("click", () => showWindow("chat"));
        notification.show();
      }
    } catch {
      /* In-app notices remain available if Windows notifications fail. */
    }
    for (const window of windows.values())
      sendToWindow(window, "reminder", item.title);
  },
});

async function startManagedOllama() {
  if (test) return;
  const executable = path.join(root, "local", "ollama", "ollama.exe");
  try {
    await fs.access(executable);
  } catch {
    return;
  }
  try {
    const response = await fetch("http://127.0.0.1:11434/api/version", {
      signal: AbortSignal.timeout(1500),
    });
    if (response.ok) return; // An existing server belongs to the user, not this app.
  } catch {
    /* Start the optional portable engine when no server is listening. */
  }
  ollamaProcess = spawn(executable, ["serve"], {
    cwd: root,
    windowsHide: true,
    env: {
      ...process.env,
      OLLAMA_HOST: "127.0.0.1:11434",
      OLLAMA_MODELS: path.join(
        process.env.WILEYAI_DATA_DIR || path.join(root, "data"),
        "models",
        "ollama",
      ),
      OLLAMA_NO_CLOUD: "1",
      OLLAMA_MAX_LOADED_MODELS: "1",
      OLLAMA_NUM_PARALLEL: "1",
    },
    stdio: "ignore",
  });
  ollamaProcess.on("error", (error) =>
    process.stderr.write("Ollama: " + error.message + "\n"),
  );
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      if (
        (
          await fetch("http://127.0.0.1:11434/api/version", {
            signal: AbortSignal.timeout(1000),
          })
        ).ok
      )
        return;
    } catch {
      /* Wait for startup. */
    }
    await new Promise((done) => setTimeout(done, 150));
  }
}

protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);
if (!app.requestSingleInstanceLock()) {
  app.quit();
}

function isAppUrl(value) {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "app:" && url.host === "wileyai") ||
      (dev && url.origin === "http://127.0.0.1:5173")
    );
  } catch {
    return false;
  }
}

function trusted(event) {
  if (isAppUrl(event.senderFrame?.url)) return;
  throw new Error("Недопустимый источник запроса");
}

async function startCore() {
  const token = randomBytes(32).toString("hex");
  const python =
    process.env.WILEYAI_PYTHON ||
    path.join(root, ".venv", "Scripts", "python.exe");
  const child = spawn(python, ["-m", "core"], {
    cwd: root,
    windowsHide: true,
    env: {
      ...process.env,
      WILEYAI_TOKEN: token,
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  core = child;
  child.stderr.on("data", (data) => process.stderr.write(data));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("Ядро не запустилось за 30 секунд")),
      30000,
    );
    let output = "";
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!quitting) {
        reject(new Error(`Ядро завершилось с кодом ${code}`));
        for (const window of windows.values())
          sendToWindow(window, "core-offline");
      }
    });
    child.stdout.on("data", async (data) => {
      output += data.toString();
      const match = output.match(/WILEYAI_PORT=(\d+)/);
      if (!match || connection) return;
      const info = { url: `http://127.0.0.1:${match[1]}`, token };
      for (let attempt = 0; attempt < 80; attempt++) {
        try {
          const response = await fetch(info.url + "/health", {
            headers: { Authorization: "Bearer " + token },
          });
          if (response.ok) {
            connection = info;
            clearTimeout(timer);
            resolve(info);
            return;
          }
        } catch {
          /* Wait for the listener; startup output is emitted before uvicorn binds. */
        }
        await new Promise((done) => setTimeout(done, 100));
      }
      clearTimeout(timer);
      reject(new Error("Ядро не отвечает после запуска"));
    });
  });
}

function showWindow(view = "chat") {
  if (!["chat", "settings", "avatar"].includes(view))
    throw new Error("Неизвестное окно");
  const existing = windows.get(view);
  if (existing && !existing.isDestroyed()) {
    existing.show();
    existing.focus();
    return;
  }
  const avatar = view === "avatar";
  const window = new BrowserWindow({
    title: avatar
      ? "WileyAI · Аватар"
      : view === "settings"
        ? "WileyAI · Настройки"
        : "WileyAI",
    width: avatar ? 360 : 1220,
    height: avatar ? 570 : 820,
    minWidth: avatar ? 300 : 900,
    minHeight: avatar ? 420 : 650,
    backgroundColor: avatar ? "#00000000" : "#101218",
    transparent: avatar,
    frame: !avatar,
    alwaysOnTop: avatar,
    autoHideMenuBar: true,
    show: false,
    icon: path.join(__dirname, "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      autoplayPolicy: "no-user-gesture-required",
    },
  });
  windows.set(view, window);
  const contentsId = window.webContents.id;
  window.webContents.on("render-process-gone", () =>
    conversation.releaseSender(contentsId),
  );
  window.webContents.on("did-navigate", () =>
    conversation.releaseSender(contentsId),
  );
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.on("close", (event) => {
    if (!quitting && !test) {
      event.preventDefault();
      window.hide();
    }
  });
  window.on("closed", () => {
    conversation.releaseSender(contentsId);
    windows.delete(view);
  });
  window.once("ready-to-show", () => window.show());
  window.loadURL(
    (dev ? "http://127.0.0.1:5173/" : "app://wileyai/") + "?view=" + view,
  );
}

app.on("second-instance", () => showWindow("chat"));
app.whenReady().then(async () => {
  protocol.handle("app", (request) => {
    const url = new URL(request.url);
    if (url.host !== "wileyai")
      return new Response("Forbidden", { status: 403 });
    const relative = decodeURIComponent(
      url.pathname === "/" ? "/index.html" : url.pathname,
    );
    const target = path.resolve(root, "dist", "." + relative);
    if (!target.startsWith(path.join(root, "dist") + path.sep))
      return new Response("Forbidden", { status: 403 });
    return net.fetch(pathToFileURL(target).href);
  });
  session.defaultSession.setPermissionRequestHandler(
    (contents, permission, callback, details) => {
      callback(
        isAppUrl(contents.getURL()) &&
          (permission === "speaker-selection" ||
            (permission === "media" &&
              details.mediaTypes?.length > 0 &&
              details.mediaTypes.every((type) => type === "audio"))),
      );
    },
  );
  session.defaultSession.setPermissionCheckHandler(
    (contents, permission, origin, details) =>
      Boolean(
        contents &&
        isAppUrl(contents.getURL()) &&
        isAppUrl(details.securityOrigin || origin) &&
        (permission === "speaker-selection" ||
          (permission === "media" && details.mediaType === "audio")),
      ),
  );
  ipcMain.handle("connection", (event) => {
    trusted(event);
    return connection;
  });
  ipcMain.handle("conversation-state", (event) => {
    trusted(event);
    return conversation.state(event.sender.id);
  });
  ipcMain.handle("conversation-acquire", (event) => {
    trusted(event);
    if (backups?.restoring)
      throw new Error("Дождитесь окончания восстановления");
    return conversation.acquire(event.sender.id);
  });
  ipcMain.handle("conversation-update", (event, id, phase) => {
    trusted(event);
    conversation.update(event.sender.id, id, phase);
  });
  ipcMain.handle("conversation-release", (event, id) => {
    trusted(event);
    conversation.release(event.sender.id, id);
  });
  ipcMain.handle("conversation-stop", (event) => {
    trusted(event);
    const owner = conversation.stop();
    for (const window of windows.values())
      if (liveContents(window)?.id === owner) sendToWindow(window, "stop-all");
  });
  ipcMain.handle("show-window", (event, view) => {
    trusted(event);
    showWindow(view);
  });
  ipcMain.handle("pick-file", async (event, kind) => {
    trusted(event);
    const filters = {
      avatar: [{ name: "VRM", extensions: ["vrm"] }],
      model: [{ name: "GGUF", extensions: ["gguf"] }],
      app: [{ name: "Приложение", extensions: ["exe", "lnk"] }],
    };
    if (!["avatar", "model", "app", "folder", "file"].includes(kind))
      throw new Error("Неизвестный тип файла");
    const result = await dialog.showOpenDialog(
      BrowserWindow.fromWebContents(event.sender),
      {
        properties: [kind === "folder" ? "openDirectory" : "openFile"],
        filters: filters[kind],
      },
    );
    return result.canceled ? null : result.filePaths[0];
  });
  ipcMain.handle("avatar-bytes", async (event) => {
    trusted(event);
    const response = await fetch(connection.url + "/settings", {
      headers: { Authorization: "Bearer " + connection.token },
    });
    const settings = await response.json();
    const file = settings.avatar_path;
    if (!file || path.extname(file).toLowerCase() !== ".vrm") return null;
    const stat = await fs.stat(file);
    if (stat.size > 64 * 1024 * 1024)
      throw new Error("Для первого прототипа выберите VRM до 64 МБ");
    return new Uint8Array(await fs.readFile(file));
  });
  ipcMain.handle("avatar-clickthrough", (event, enabled) => {
    trusted(event);
    const window = BrowserWindow.fromWebContents(event.sender);
    if (windows.get("avatar") === window)
      window.setIgnoreMouseEvents(Boolean(enabled), { forward: true });
  });
  ipcMain.handle("quit", (event) => {
    trusted(event);
    app.quit();
  });
  backups = installBackups({
    ipcMain,
    dialog,
    BrowserWindow,
    trusted,
    getConnection: () => connection,
    isBusy: () => Boolean(conversation.lease || deliverNotifications.active),
    restored: () => {
      for (const window of windows.values())
        sendToWindow(window, "data-restored");
    },
  });
  try {
    await startCore();
    await startManagedOllama();
    showWindow("chat");
    if (!test) {
      app.setAppUserModelId("WileyAI");
      notificationTimer = setInterval(deliverNotifications, 2500);
      tray = new Tray(
        nativeImage.createFromPath(path.join(__dirname, "icon.png")),
      );
      tray.setToolTip("WileyAI");
      tray.setContextMenu(
        Menu.buildFromTemplate([
          { label: "Чат", click: () => showWindow("chat") },
          { label: "Настройки", click: () => showWindow("settings") },
          {
            label: "Аватар",
            click: () => {
              windows.get("avatar")?.setIgnoreMouseEvents(false);
              showWindow("avatar");
            },
          },
          { type: "separator" },
          { label: "Выйти", click: () => app.quit() },
        ]),
      );
      tray.on("double-click", () => showWindow("chat"));
      globalShortcut.register("CommandOrControl+Shift+Space", () =>
        showWindow("chat"),
      );
      globalShortcut.register("CommandOrControl+Shift+Escape", () => {
        conversation.stop();
        for (const window of windows.values()) sendToWindow(window, "stop-all");
        windows.get("avatar")?.setIgnoreMouseEvents(false);
      });
    }
  } catch (error) {
    dialog.showErrorBox(
      "WileyAI не запустился",
      error.message +
        "\nПодготовка: uv sync --extra dev, npm install, npm run build",
    );
    app.quit();
  }
});
app.on("window-all-closed", () => {
  if (test) app.quit();
});
app.on("before-quit", (event) => {
  if (quitting) return;
  event.preventDefault();
  quitting = true;
  conversation.stop();
  for (const window of windows.values()) sendToWindow(window, "stop-all");
  clearInterval(notificationTimer);
  globalShortcut.unregisterAll();
  const stopSpeech = connection
    ? fetch(connection.url + "/voice/stop", {
        method: "POST",
        headers: { Authorization: "Bearer " + connection.token },
        signal: AbortSignal.timeout(1500),
      }).catch(() => {})
    : Promise.resolve();
  stopSpeech.finally(() => {
    if (process.platform === "win32") {
      // Only kill process trees created and owned by this application.
      if (core?.pid && core.exitCode === null)
        spawn("taskkill.exe", ["/PID", String(core.pid), "/T", "/F"], {
          windowsHide: true,
          stdio: "ignore",
        });
      if (ollamaProcess?.pid && ollamaProcess.exitCode === null)
        spawn("taskkill.exe", ["/PID", String(ollamaProcess.pid), "/T", "/F"], {
          windowsHide: true,
          stdio: "ignore",
        });
    } else {
      core?.kill();
      ollamaProcess?.kill();
    }
    app.quit();
  });
});
