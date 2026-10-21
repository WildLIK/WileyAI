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
  shell,
  screen,
  powerMonitor,
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
const { APP_ID } = require("./identity.cjs");
const { CoreConnection, portFromOutput } = require("./core-connection.cjs");
const { startupPreferences } = require("./startup.cjs");
const { installAvatar } = require("./avatar.cjs");
const { installAvatarLayout } = require("./avatar-layout.cjs");
const {
  avatarTrayItems,
  installAvatarControls,
} = require("./avatar-controls.cjs");

const root = path.resolve(__dirname, "..");
const backend = app.isPackaged
  ? path.join(process.resourcesPath, "backend")
  : root;
const dev = process.env.WILEYAI_DEV === "1";
const test = process.env.WILEYAI_TEST === "1";
const startup = startupPreferences(app, { test });
if (test && process.env.WILEYAI_DATA_DIR)
  app.setPath("userData", path.join(process.env.WILEYAI_DATA_DIR, "electron"));
const dataRoot =
  process.env.WILEYAI_DATA_DIR ||
  (app.isPackaged
    ? path.join(app.getPath("userData"), "data")
    : path.join(root, "data"));
const python =
  process.env.WILEYAI_PYTHON ||
  (app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "python", "python.exe")
    : path.join(root, ".venv", "Scripts", "python.exe"));
const serviceEnv = {
  ...process.env,
  WILEYAI_DATA_DIR: dataRoot,
  ...(app.isPackaged
    ? {
        WILEYAI_PACKAGED: "1",
        WILEYAI_UV: path.join(
          process.resourcesPath,
          "runtime",
          "tools",
          "uv.exe",
        ),
        WILEYAI_OPENVOICE_CACHE: path.join(dataRoot, "runtimes", "openvoice"),
      }
    : {}),
};
const windows = new Map();
let avatarDesktop;
let avatarLayout;
let avatarControls;
let core;
let connection;
const coreConnection = new CoreConnection();
let tray;
let quitting = false;
let ollamaProcess;
let notificationTimer;
let updateTimer;
let backups;
function spawnService(executable, args, options) {
  if (process.platform !== "win32") return spawn(executable, args, options);
  return spawn(
    python,
    ["-m", "core.process_guard", String(process.pid), executable, ...args],
    options,
  );
}
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
  let executable = path.join(root, "local", "ollama", "ollama.exe");
  try {
    const marker = JSON.parse(
      await fs.readFile(
        path.join(dataRoot, "components", "ollama", "ready.json"),
        "utf8",
      ),
    );
    if (/^[a-f0-9]{16}$/.test(marker.directory))
      executable = path.join(
        dataRoot,
        "components",
        "ollama",
        marker.directory,
        "ollama.exe",
      );
  } catch {
    /* Source checkout may have the legacy portable engine. */
  }
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
  ollamaProcess = spawnService(executable, ["serve"], {
    cwd: backend,
    windowsHide: true,
    env: {
      ...serviceEnv,
      OLLAMA_HOST: "127.0.0.1:11434",
      OLLAMA_MODELS: path.join(dataRoot, "models", "ollama"),
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
const primary = app.requestSingleInstanceLock();
if (!primary) {
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
  const child = spawnService(python, ["-m", "core"], {
    cwd: backend,
    windowsHide: true,
    env: {
      ...serviceEnv,
      WILEYAI_TOKEN: token,
      WILEYAI_DESKTOP_PID: String(process.pid),
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
    let probing = false;
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (!quitting) {
        const error = new Error(
          `Ядро завершилось с кодом ${code}. Перезапустите WileyAI.`,
        );
        connection = undefined;
        coreConnection.fail(error);
        reject(error);
        for (const window of windows.values())
          sendToWindow(window, "core-offline");
      }
    });
    child.stdout.on("data", async (data) => {
      output += data.toString();
      const port = portFromOutput(output);
      if (!port || connection || probing || quitting) return;
      probing = true;
      const info = { url: `http://127.0.0.1:${port}`, token };
      for (let attempt = 0; attempt < 80; attempt++) {
        try {
          const response = await fetch(info.url + "/health", {
            headers: { Authorization: "Bearer " + token },
            signal: AbortSignal.timeout(1000),
          });
          if (response.ok) {
            if (quitting || !coreConnection.ready(info)) return;
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

function refreshTrayMenu() {
  if (!tray || tray.isDestroyed()) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Чат", click: () => showWindow("chat") },
      { label: "Настройки", click: () => showWindow("settings") },
      ...avatarTrayItems(avatarControls, () => showWindow("avatar")),
      { type: "separator" },
      { label: "Выйти", click: () => app.quit() },
    ]),
  );
}

function showWindow(view = "chat") {
  if (!["chat", "settings", "avatar", "avatar-test"].includes(view))
    throw new Error("Неизвестное окно");
  if (view === "avatar-test") showWindow("avatar");
  if (view === "avatar") avatarControls?.setClickThrough(false);
  const existing = windows.get(view);
  if (existing && !existing.isDestroyed()) {
    if (existing.isMinimized()) existing.restore();
    existing.show();
    existing.focus();
    if (view === "avatar-test") avatarLayout.arrange();
    return;
  }
  const avatar = view === "avatar";
  const tool = view === "avatar-test";
  const window = new BrowserWindow({
    title: avatar
      ? "WileyAI · Аватар"
      : tool
        ? "WileyAI · Эмоции и позы"
        : view === "settings"
          ? "WileyAI · Настройки"
          : "WileyAI",
    width: avatar ? 480 : tool ? 340 : 1220,
    height: avatar ? 740 : tool ? 540 : 820,
    ...(avatar ? avatarLayout.initial() : {}),
    minWidth: avatar || tool ? 300 : 900,
    minHeight: avatar || tool ? 420 : 650,
    resizable: true,
    backgroundColor: avatar ? "#00000000" : "#101218",
    transparent: avatar,
    frame: !avatar,
    alwaysOnTop: avatar || tool,
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
  avatarDesktop?.watch(window);
  avatarLayout.watch(window, view);
  avatarControls.watch(window, view);
  const reportActivity = () =>
    sendToWindow(window, "window-activity", windowActivity(window));
  for (const event of ["show", "hide", "minimize", "restore", "focus", "blur"])
    window.on(event, reportActivity);
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
    if (!quitting && !test && !tool) {
      event.preventDefault();
      if (avatar) avatarControls.hide();
      else window.hide();
    }
  });
  window.on("closed", () => {
    conversation.releaseSender(contentsId);
    windows.delete(view);
    const toolWindow = windows.get("avatar-test");
    if (avatar && toolWindow && !toolWindow.isDestroyed()) toolWindow.close();
  });
  window.once("ready-to-show", () => {
    if (tool) avatarLayout.arrange();
    window.show();
  });
  window.loadURL(
    (dev ? "http://127.0.0.1:5173/" : "app://wileyai/") + "?view=" + view,
  );
}

app.on("second-instance", () => showWindow("chat"));
function windowActivity(window) {
  return {
    visible: Boolean(
      window &&
      !avatarDesktop?.paused &&
      !window.isDestroyed() &&
      window.isVisible() &&
      !window.isMinimized(),
    ),
    focused: Boolean(window && !window.isDestroyed() && window.isFocused()),
  };
}
app.whenReady().then(async () => {
  if (!primary) return;
  avatarControls = installAvatarControls({
    ipcMain,
    BrowserWindow,
    windows,
    screen,
    trusted,
    sendToWindow,
    changed: refreshTrayMenu,
    paused: () => Boolean(avatarDesktop?.paused),
  });
  avatarLayout = installAvatarLayout({
    ipcMain,
    BrowserWindow,
    screen,
    windows,
    trusted,
    sendToWindow,
    dataRoot,
  });
  avatarDesktop = installAvatar({
    ipcMain,
    BrowserWindow,
    windows,
    trusted,
    sendToWindow,
    screen,
    powerMonitor,
    activity: (window) =>
      sendToWindow(window, "window-activity", windowActivity(window)),
    stop: () => {
      conversation.stop();
      for (const window of windows.values()) sendToWindow(window, "stop-all");
    },
  });
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
    return coreConnection.wait();
  });
  ipcMain.handle("window-activity", (event) => {
    trusted(event);
    return windowActivity(BrowserWindow.fromWebContents(event.sender));
  });
  ipcMain.handle("restart", (event) => {
    trusted(event);
    if (backups?.restoring || conversation.lease)
      throw new Error(
        "Завершите разговор или восстановление перед перезапуском",
      );
    app.relaunch();
    app.quit();
  });
  ipcMain.handle("startup-get", (event) => {
    trusted(event);
    return startup.get();
  });
  ipcMain.handle("startup-set", (event, enabled) => {
    trusted(event);
    return startup.set(enabled);
  });
  ipcMain.handle("start-ollama", async (event) => {
    trusted(event);
    await startManagedOllama();
  });
  ipcMain.handle("open-update", async (event) => {
    trusted(event);
    // Only a fixed repository page can be opened, never a renderer-supplied URL.
    await shell.openExternal("https://github.com/WildLIK/WileyAI/releases");
  });
  async function googleLogin(event, endpoint) {
    trusted(event);
    const connection = await coreConnection.wait();
    const response = await fetch(connection.url + endpoint, {
      method: "POST",
      headers: { Authorization: "Bearer " + connection.token },
      signal: AbortSignal.timeout(15000),
      redirect: "error",
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(data.detail || "Не удалось начать вход Google");
    const url = new URL(data.url);
    if (
      url.origin !== "https://accounts.google.com" ||
      url.pathname !== "/o/oauth2/v2/auth" ||
      url.username ||
      url.password
    )
      throw new Error("Недопустимый адрес входа Google");
    await shell.openExternal(url.href);
  }
  ipcMain.handle("google-calendar-login", (event) =>
    googleLogin(event, "/calendar/google/login"),
  );
  ipcMain.handle("gmail-login", (event) =>
    googleLogin(event, "/mail/gmail/login"),
  );
  ipcMain.handle("gmail-send-login", (event) =>
    googleLogin(event, "/mail/gmail/send-login"),
  );
  ipcMain.handle("gmail-drafts-login", (event) =>
    googleLogin(event, "/mail/gmail/drafts-login"),
  );
  ipcMain.handle("mail-export", async (event, options) => {
    trusted(event);
    if (
      !options ||
      typeof options.id !== "string" ||
      typeof options.conversationId !== "string" ||
      !/^[A-Za-z0-9_-]{1,64}$/.test(options.id) ||
      !/^[A-Za-z0-9_-]{1,64}$/.test(options.conversationId) ||
      typeof options.updated !== "string" ||
      options.updated.length > 100
    )
      throw new Error("Некорректный черновик для сохранения");
    const connection = await coreConnection.wait();
    const query = new URLSearchParams({
      conversation_id: options.conversationId,
      expected_updated: options.updated,
    });
    const response = await fetch(
      connection.url + "/mail/drafts/" + options.id + "/eml?" + query,
      {
        headers: { Authorization: "Bearer " + connection.token },
        signal: AbortSignal.timeout(15000),
        redirect: "error",
      },
    );
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : "Не удалось подготовить файл письма",
      );
    }
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > 16 * 1024 * 1024)
      throw new Error("Письмо превышает 16 МБ");
    const result = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender),
      {
        title: "Сохранить неотправленный черновик",
        defaultPath: "WileyAI-draft.eml",
        filters: [{ name: "Черновик письма", extensions: ["eml"] }],
      },
    );
    if (result.canceled || !result.filePath) return null;
    if (!result.filePath.toLowerCase().endsWith(".eml"))
      throw new Error("Выберите имя файла с расширением .eml");
    const temporary =
      result.filePath + "." + randomBytes(8).toString("hex") + ".tmp";
    const handle = await fs.open(temporary, "wx", 0o600);
    try {
      try {
        await handle.writeFile(bytes);
        await handle.sync();
      } finally {
        await handle.close();
      }
      // The native dialog confirms replacing an existing destination. Rename
      // only a completed, flushed file, so a failed write preserves that file.
      await fs.rename(temporary, result.filePath);
    } finally {
      await fs.unlink(temporary).catch((error) => {
        if (error.code !== "ENOENT") throw error;
      });
    }
    return { path: result.filePath };
  });
  ipcMain.handle("conversation-state", (event) => {
    trusted(event);
    return conversation.state(event.sender.id);
  });
  ipcMain.handle("mail-attachment-export", async (event, options) => {
    trusted(event);
    if (
      !options ||
      !/^[a-f0-9]{48}$/.test(options.ticket) ||
      !/^[A-Za-z0-9_-]{1,64}$/.test(options.conversationId)
    )
      throw new Error("Некорректное вложение");
    const info = await coreConnection.wait();
    const response = await fetch(
      info.url +
        "/mail/attachments/" +
        options.ticket +
        "?conversation_id=" +
        encodeURIComponent(options.conversationId),
      {
        headers: { Authorization: "Bearer " + info.token },
        signal: AbortSignal.timeout(30000),
        redirect: "error",
      },
    );
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(
        typeof error.detail === "string"
          ? error.detail
          : "Не удалось скачать вложение",
      );
    }
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > 5 * 1024 * 1024)
      throw new Error("Вложение превышает 5 МБ");
    const name = String(options.name || "attachment.bin")
      .split(/[\\/]/)
      .pop()
      .replace(/[<>:"|?*\x00-\x1f]/g, "_")
      .slice(0, 180);
    const result = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender),
      { title: "Сохранить вложение", defaultPath: "WileyAI-" + name },
    );
    if (result.canceled || !result.filePath) return null;
    const temporary =
      result.filePath + "." + randomBytes(8).toString("hex") + ".tmp";
    const handle = await fs.open(temporary, "wx", 0o600);
    try {
      try {
        await handle.writeFile(bytes);
        await handle.sync();
      } finally {
        await handle.close();
      }
      await fs.rename(temporary, result.filePath);
    } finally {
      await fs.unlink(temporary).catch((error) => {
        if (error.code !== "ENOENT") throw error;
      });
    }
    return { path: result.filePath };
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
    const current = await coreConnection.wait();
    const response = await fetch(current.url + "/settings", {
      headers: { Authorization: "Bearer " + current.token },
    });
    if (!response.ok) throw new Error("Не удалось получить настройки аватара");
    const settings = await response.json();
    const file = settings.avatar_path;
    if (!file || path.extname(file).toLowerCase() !== ".vrm") return null;
    const stat = await fs.stat(file);
    if (stat.size > 64 * 1024 * 1024)
      throw new Error("Для первого прототипа выберите VRM до 64 МБ");
    return new Uint8Array(await fs.readFile(file));
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
    if (!app.isPackaged || !process.argv.includes("--autostart") || test)
      showWindow("chat");
    if (!test) {
      app.setAppUserModelId(app.isPackaged ? APP_ID : "WileyAI");
      notificationTimer = setInterval(deliverNotifications, 2500);
      let updatePolling = false;
      updateTimer = setInterval(async () => {
        if (updatePolling || quitting || backups?.restoring) return;
        updatePolling = true;
        try {
          const response = await fetch(connection.url + "/updates/claim", {
            method: "POST",
            headers: { Authorization: "Bearer " + connection.token },
            signal: AbortSignal.timeout(3000),
          });
          const item = response.ok ? await response.json() : null;
          if (item && Notification.isSupported()) {
            const notification = new Notification({
              title: "Новая версия WileyAI",
              body:
                "Доступна версия " +
                item.version +
                ". Откройте выпуск на GitHub.",
              icon: path.join(__dirname, "icon.png"),
            });
            notification.on("click", () =>
              shell.openExternal("https://github.com/WildLIK/WileyAI/releases"),
            );
            notification.show();
          }
        } catch {
          /* Update errors are shown in settings; the assistant stays usable. */
        } finally {
          updatePolling = false;
        }
      }, 60000);
      tray = new Tray(
        nativeImage.createFromPath(path.join(__dirname, "icon.png")),
      );
      tray.setToolTip("WileyAI");
      refreshTrayMenu();
      tray.on("double-click", () => showWindow("chat"));
      globalShortcut.register("CommandOrControl+Shift+Space", () =>
        showWindow("chat"),
      );
      globalShortcut.register("CommandOrControl+Shift+Escape", () => {
        conversation.stop();
        for (const window of windows.values()) sendToWindow(window, "stop-all");
        avatarControls.setClickThrough(false);
      });
      globalShortcut.register("CommandOrControl+Alt+A", () =>
        avatarControls.setClickThrough(!avatarControls.state().clickThrough),
      );
    }
  } catch (error) {
    coreConnection.fail(error);
    if (quitting) return;
    dialog.showErrorBox(
      "WileyAI не запустился",
      error.message +
        (app.isPackaged
          ? "\nПереустановите WileyAI из готового установщика. Личные данные сохраняются отдельно."
          : "\nПодготовка: uv sync --extra dev, npm install, npm run build"),
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
  coreConnection.fail(new Error("WileyAI завершает работу"));
  conversation.stop();
  for (const window of windows.values()) sendToWindow(window, "stop-all");
  clearInterval(notificationTimer);
  clearInterval(updateTimer);
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
