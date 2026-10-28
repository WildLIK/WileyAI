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
const { avatarFile } = require("./avatar-file.cjs");
const { installAvatarLayout } = require("./avatar-layout.cjs");
const {
  avatarTrayItems,
  installAvatarControls,
} = require("./avatar-controls.cjs");

const root = path.resolve(__dirname, "..");
const backend = app.isPackaged
  ? path.join(process.resourcesPath, "backend")
  : root;
// Developer overrides never apply to an installed build. WILEYAI_DATA_DIR stays
// available there: the packaged smoke test runs against an isolated profile.
const dev = !app.isPackaged && process.env.WILEYAI_DEV === "1";
const test = process.env.WILEYAI_TEST === "1";
const startup = startupPreferences(app, { test });
if (test && process.env.WILEYAI_DATA_DIR)
  app.setPath("userData", path.join(process.env.WILEYAI_DATA_DIR, "electron"));
const dataRoot =
  process.env.WILEYAI_DATA_DIR ||
  (app.isPackaged
    ? path.join(app.getPath("userData"), "data")
    : path.join(root, "data"));
const python = app.isPackaged
  ? path.join(process.resourcesPath, "runtime", "python", "python.exe")
  : process.env.WILEYAI_PYTHON ||
    path.join(root, ".venv", "Scripts", "python.exe");
// The bundled runtime ignores PYTHON* variables and the user site directory;
// -E also drops PYTHONIOENCODING/PYTHONUNBUFFERED, hence -X utf8 -u.
const pythonFlags = app.isPackaged ? ["-E", "-s", "-X", "utf8", "-u"] : [];
const serviceEnv = {
  ...Object.fromEntries(
    Object.entries(process.env).filter(
      ([key]) => !app.isPackaged || !/^PYTHON/i.test(key),
    ),
  ),
  WILEYAI_DATA_DIR: dataRoot,
  ...(app.isPackaged
    ? {
        PYTHONNOUSERSITE: "1",
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
// Attachment types that run code or macros when opened.
const RISKY_EXTENSIONS = new Set(
  (
    "exe scr bat cmd com pif ps1 psm1 vbs vbe js jse wsf wsh hta lnk url msi " +
    "msp reg cpl jar dll sys inf scf application appref-ms gadget msc iso img " +
    "vhd vhdx docm dotm xlsm xltm xlam pptm potm ppam sldm"
  ).split(" "),
);
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
// Windows drops click handlers of garbage-collected notifications.
const notifications = new Set();
function showNotification(options, click) {
  const notification = new Notification(options);
  notifications.add(notification);
  const forget = () => notifications.delete(notification);
  notification.on("click", () => {
    forget();
    click();
  });
  notification.on("close", forget);
  notification.on("failed", forget);
  notification.show();
}
function spawnService(executable, args, options) {
  if (process.platform !== "win32") return spawn(executable, args, options);
  return spawn(
    python,
    [
      ...pythonFlags,
      "-m",
      "core.process_guard",
      String(process.pid),
      executable,
      ...args,
    ],
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
      if (Notification.isSupported())
        showNotification(
          {
            title:
              item.kind === "calendar"
                ? "WileyAI · Встреча"
                : "WileyAI · Напоминание",
            body: item.title,
            icon: path.join(__dirname, "icon.png"),
          },
          () => showWindow("chat"),
        );
    } catch {
      /* In-app notices remain available if Windows notifications fail. */
    }
    for (const window of windows.values())
      sendToWindow(window, "reminder", item.title);
  },
});

// Startup and the settings button share one attempt; a live child is reused.
let ollamaStarting;
function startManagedOllama() {
  if (test || quitting) return Promise.resolve();
  ollamaStarting ||= launchOllama().finally(() => {
    ollamaStarting = undefined;
  });
  return ollamaStarting;
}
async function launchOllama() {
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
  if (quitting) return;
  if (ollamaProcess) {
    // Our engine is still running but slow to answer; do not start a second one.
    if (ollamaProcess.exitCode === null && ollamaProcess.signalCode === null)
      return;
    ollamaProcess = undefined;
  }
  const child = spawnService(executable, ["serve"], {
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
  ollamaProcess = child;
  const forget = () => {
    if (ollamaProcess === child) ollamaProcess = undefined;
  };
  child.on("error", (error) => {
    forget();
    process.stderr.write("Ollama: " + error.message + "\n");
  });
  child.on("exit", forget);
  for (let attempt = 0; attempt < 30; attempt++) {
    if (ollamaProcess !== child) return;
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
  const child = spawnService(python, [...pythonFlags, "-m", "core"], {
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
    // First launch can be slow while Windows Defender scans the bundled runtime.
    const timer = setTimeout(
      () => reject(new Error("Ядро не запустилось за 120 секунд")),
      120000,
    );
    let output = "";
    let probing = false;
    child.stdout.setEncoding("utf8");
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
    child.stdout.on("data", async (text) => {
      // Keep draining stdout, but only buffer the unfinished line before the port.
      if (probing) return;
      const lines = (output + text).split("\n");
      output = lines.pop().slice(-4096);
      const port = lines
        .map((line) => portFromOutput(line + "\n"))
        .find(Boolean);
      if (!port || connection || quitting) return;
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

// Quitting mid-restore would leave the profile half replaced.
function requestQuit(window) {
  if (!backups?.restoring) return app.quit();
  const options = {
    type: "info",
    title: "WileyAI",
    message:
      "Идёт восстановление из резервной копии. Выйти можно после его завершения.",
  };
  void (window && !window.isDestroyed()
    ? dialog.showMessageBox(window, options)
    : dialog.showMessageBox(options));
}

// The session is ending: let windows close and Electron exit without waiting.
// The process guard ends core and Ollama together with this process.
function endSession() {
  if (quitting) return;
  quitting = true;
  coreConnection.fail(new Error("WileyAI завершает работу"));
  clearInterval(notificationTimer);
  clearInterval(updateTimer);
  globalShortcut.unregisterAll();
  app.quit();
}

function refreshTrayMenu() {
  if (!tray || tray.isDestroyed()) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Чат", click: () => showWindow("chat") },
      { label: "Настройки", click: () => showWindow("settings") },
      ...avatarTrayItems(avatarControls, () => showWindow("avatar")),
      { type: "separator" },
      { label: "Выйти", click: () => requestQuit() },
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
      devTools: !app.isPackaged,
    },
  });
  windows.set(view, window);
  if (avatar) {
    // The transparent avatar has no visible zoom state to undo; keep it at 100%.
    window.webContents.setVisualZoomLevelLimits(1, 1).catch(() => {});
    window.webContents.on("before-input-event", (event, input) => {
      if (
        input.type === "keyDown" &&
        (input.control || input.meta) &&
        ["+", "=", "-", "_", "0"].includes(input.key)
      )
        event.preventDefault();
    });
    window.webContents.on("zoom-changed", () =>
      window.webContents.setZoomLevel(0),
    );
  } else if (app.isPackaged) {
    // Without the default menu its zoom accelerators are gone; keep them for reading.
    window.webContents.on("before-input-event", (event, input) => {
      if (input.type !== "keyDown" || !(input.control || input.meta)) return;
      const step = { "+": 0.5, "=": 0.5, "-": -0.5, _: -0.5 }[input.key];
      if (step === undefined && input.key !== "0") return;
      event.preventDefault();
      const level =
        step === undefined ? 0 : window.webContents.getZoomLevel() + step;
      window.webContents.setZoomLevel(Math.max(-3, Math.min(3, level)));
    });
  }
  // Windows shutdown/logoff closes windows; never turn that into "hide to tray".
  window.on("session-end", endSession);
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
  // Before any window or notification, so Windows groups them under this app.
  if (!test) app.setAppUserModelId(app.isPackaged ? APP_ID : "WileyAI");
  // The default menu exposes DevTools, reload and zoom accelerators.
  if (app.isPackaged) Menu.setApplicationMenu(null);
  avatarControls = installAvatarControls({
    ipcMain,
    BrowserWindow,
    windows,
    screen,
    trusted,
    sendToWindow,
    changed: refreshTrayMenu,
    paused: () => Boolean(avatarDesktop?.paused),
    dataRoot,
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
  ipcMain.handle("chatgpt-login", async (event, newAccount = false) => {
    trusted(event);
    if (typeof newAccount !== "boolean")
      throw new Error("Некорректный вариант входа ChatGPT");
    const current = await coreConnection.wait();
    const response = await fetch(
      current.url + "/chatgpt/login?new_account=" + newAccount,
      {
        method: "POST",
        headers: { Authorization: "Bearer " + current.token },
        signal: AbortSignal.timeout(45000),
        redirect: "error",
      },
    );
    const data = await response.json();
    if (!response.ok)
      throw new Error(data.detail || "Не удалось начать вход ChatGPT");
    const url = new URL(data.url);
    if (
      url.origin !== "https://auth.openai.com" ||
      url.pathname !== "/api/accounts/authorize" ||
      url.username ||
      url.password ||
      url.hash
    )
      throw new Error("Недопустимый адрес входа ChatGPT");
    try {
      await shell.openExternal(url.href);
    } catch {
      // Launch errors can contain the URL's sensitive ID-token hint.
      await fetch(current.url + "/chatgpt/cancel", {
        method: "POST",
        headers: { Authorization: "Bearer " + current.token },
        signal: AbortSignal.timeout(5000),
      }).catch(() => {});
      throw new Error(
        "Не удалось открыть браузер для входа ChatGPT. Повторите вход.",
      );
    }
  });
  ipcMain.handle("chatgpt-usage", async (event) => {
    trusted(event);
    await shell.openExternal("https://chatgpt.com/settings/usage");
  });
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
      .slice(0, 180)
      .replace(/[. ]+$/, ""); // Windows drops these, which would hide ".exe."
    const owner = BrowserWindow.fromWebContents(event.sender);
    const extension = path.extname(name).slice(1).toLowerCase();
    if (
      RISKY_EXTENSIONS.has(extension) &&
      (
        await dialog.showMessageBox(owner, {
          type: "warning",
          title: "Опасное вложение",
          message: `Файл «${name}» может запустить программу или макрос.`,
          detail:
            "Сохраняйте и открывайте его, только если доверяете отправителю. Windows пометит файл как скачанный из интернета.",
          buttons: ["Сохранить", "Отмена"],
          defaultId: 1,
          cancelId: 1,
          noLink: true,
        })
      ).response !== 0
    )
      return null;
    const result = await dialog.showSaveDialog(owner, {
      title: "Сохранить вложение",
      defaultPath: "WileyAI-" + name,
      ...(extension
        ? { filters: [{ name: "." + extension, extensions: [extension] }] }
        : {}),
    });
    if (result.canceled || !result.filePath) return null;
    // The warning above was about the original type; renaming cannot bypass it.
    const chosen = path.extname(result.filePath).slice(1).toLowerCase();
    if (extension ? chosen !== extension : RISKY_EXTENSIONS.has(chosen))
      throw new Error(
        extension
          ? "Сохраните вложение с исходным расширением ." + extension
          : "Выберите имя файла без исполняемого расширения",
      );
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
    // Mark of the Web: SmartScreen and Office treat the file as downloaded.
    await fs
      .writeFile(
        result.filePath + ":Zone.Identifier",
        "[ZoneTransfer]\r\nZoneId=3\r\n",
      )
      .catch(() => {
        /* FAT/exFAT and network shares may not support alternate streams. */
      });
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
      signal: AbortSignal.timeout(15000),
      redirect: "error",
    });
    if (!response.ok) throw new Error("Не удалось получить настройки аватара");
    const settings = await response.json();
    const file = avatarFile(
      settings.avatar_path,
      app.isPackaged ? process.resourcesPath : path.join(root, "assets"),
    );
    if (!file) return null;
    const stat = await fs.stat(file);
    if (!stat.isFile()) throw new Error("Выберите файл модели VRM");
    if (stat.size > 64 * 1024 * 1024)
      throw new Error("Для первого прототипа выберите VRM до 64 МБ");
    return new Uint8Array(await fs.readFile(file));
  });
  ipcMain.handle("quit", (event) => {
    trusted(event);
    requestQuit(BrowserWindow.fromWebContents(event.sender));
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
    if (!test) {
      tray = new Tray(
        nativeImage.createFromPath(path.join(__dirname, "icon.png")),
      );
      tray.setToolTip("WileyAI");
      refreshTrayMenu();
      tray.on("double-click", () => showWindow("chat"));
    }
    if (!app.isPackaged || !process.argv.includes("--autostart") || test)
      showWindow("chat");
    // Windows do not need the optional engine; the core reaches it per request.
    void startManagedOllama().catch((error) =>
      process.stderr.write("Ollama: " + error.message + "\n"),
    );
    if (!test) {
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
          if (item && Notification.isSupported())
            showNotification(
              {
                title: "Новая версия WileyAI",
                body:
                  "Доступна версия " +
                  item.version +
                  ". Откройте выпуск на GitHub.",
                icon: path.join(__dirname, "icon.png"),
              },
              () =>
                shell.openExternal(
                  "https://github.com/WildLIK/WileyAI/releases",
                ),
            );
        } catch {
          /* Update errors are shown in settings; the assistant stays usable. */
        } finally {
          updatePolling = false;
        }
      }, 60000);
      const shortcuts = {
        "CommandOrControl+Shift+Space": () => showWindow("chat"),
        // Ctrl+Shift+Esc belongs to Task Manager and cannot be registered.
        "CommandOrControl+Alt+Escape": () => {
          conversation.stop();
          for (const window of windows.values())
            sendToWindow(window, "stop-all");
          avatarControls.setClickThrough(false);
        },
        "CommandOrControl+Alt+A": () =>
          avatarControls.setClickThrough(!avatarControls.state().clickThrough),
        "CommandOrControl+Alt+H": () =>
          avatarControls.setMinimal(!avatarControls.state().minimal),
      };
      for (const [accelerator, action] of Object.entries(shortcuts))
        if (!globalShortcut.register(accelerator, action))
          console.warn(
            "WileyAI: global shortcut is taken by another app:",
            accelerator,
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
