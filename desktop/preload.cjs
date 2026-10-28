const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wiley", {
  connection: () => ipcRenderer.invoke("connection"),
  windowActivity: () => ipcRenderer.invoke("window-activity"),
  onWindowActivity: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("window-activity", listener);
    return () => ipcRenderer.removeListener("window-activity", listener);
  },
  showWindow: (view) => ipcRenderer.invoke("show-window", view),
  pickFile: (kind) => ipcRenderer.invoke("pick-file", kind),
  avatarBytes: () => ipcRenderer.invoke("avatar-bytes"),
  avatarSize: () => ipcRenderer.invoke("avatar-size-get"),
  resizeAvatar: (size) => ipcRenderer.invoke("avatar-size-set", size),
  onAvatarSize: (callback) => {
    const listener = (_event, size) => callback(size);
    ipcRenderer.on("avatar-size", listener);
    return () => ipcRenderer.removeListener("avatar-size", listener);
  },
  closeAvatarTest: () => ipcRenderer.invoke("avatar-test-close"),
  avatarCapabilities: () => ipcRenderer.invoke("avatar-capabilities-get"),
  reportAvatarCapabilities: (value) =>
    ipcRenderer.invoke("avatar-capabilities-update", value),
  onAvatarCapabilities: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("avatar-capabilities", listener);
    return () => ipcRenderer.removeListener("avatar-capabilities", listener);
  },
  watchAvatarPointer: (enabled) =>
    ipcRenderer.invoke("avatar-pointer-watch", enabled),
  onAvatarPointer: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("avatar-pointer", listener);
    return () => ipcRenderer.removeListener("avatar-pointer", listener);
  },
  avatarState: () => ipcRenderer.invoke("avatar-state-get"),
  updateAvatar: (value) => ipcRenderer.invoke("avatar-state-update", value),
  avatarDemo: () => ipcRenderer.invoke("avatar-demo-get"),
  updateAvatarDemo: (value, renew = false) =>
    ipcRenderer.invoke("avatar-demo-update", value, renew),
  releaseAvatarDemo: () => ipcRenderer.invoke("avatar-demo-release"),
  onAvatarDemo: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("avatar-demo", listener);
    return () => ipcRenderer.removeListener("avatar-demo", listener);
  },
  onAvatarState: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("avatar-state", listener);
    return () => ipcRenderer.removeListener("avatar-state", listener);
  },
  nextAvatarDisplay: () => ipcRenderer.invoke("avatar-next-display"),
  clickThrough: (enabled) => ipcRenderer.invoke("avatar-clickthrough", enabled),
  avatarControls: () => ipcRenderer.invoke("avatar-controls-get"),
  hideAvatar: () => ipcRenderer.invoke("avatar-hide"),
  minimalAvatar: (enabled) => ipcRenderer.invoke("avatar-minimal", enabled),
  setAvatarControlRegions: (regions) =>
    ipcRenderer.invoke("avatar-control-regions", regions),
  onAvatarControls: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("avatar-controls", listener);
    return () => ipcRenderer.removeListener("avatar-controls", listener);
  },
  quit: () => ipcRenderer.invoke("quit"),
  restart: () => ipcRenderer.invoke("restart"),
  startup: () => ipcRenderer.invoke("startup-get"),
  setStartup: (enabled) => ipcRenderer.invoke("startup-set", enabled),
  startOllama: () => ipcRenderer.invoke("start-ollama"),
  openUpdate: () => ipcRenderer.invoke("open-update"),
  googleCalendarLogin: () => ipcRenderer.invoke("google-calendar-login"),
  chatgptLogin: (newAccount = false) =>
    ipcRenderer.invoke("chatgpt-login", newAccount),
  chatgptUsage: () => ipcRenderer.invoke("chatgpt-usage"),
  gmailLogin: () => ipcRenderer.invoke("gmail-login"),
  gmailSendLogin: () => ipcRenderer.invoke("gmail-send-login"),
  gmailDraftsLogin: () => ipcRenderer.invoke("gmail-drafts-login"),
  exportMail: (options) => ipcRenderer.invoke("mail-export", options),
  exportAttachment: (options) =>
    ipcRenderer.invoke("mail-attachment-export", options),
  exportBackup: () => ipcRenderer.invoke("backup-export"),
  previewBackup: () => ipcRenderer.invoke("backup-preview"),
  restoreBackup: (options) => ipcRenderer.invoke("backup-restore", options),
  onDataRestored: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("data-restored", listener);
    return () => ipcRenderer.removeListener("data-restored", listener);
  },
  conversationState: () => ipcRenderer.invoke("conversation-state"),
  acquireConversation: () => ipcRenderer.invoke("conversation-acquire"),
  updateConversation: (id, phase) =>
    ipcRenderer.invoke("conversation-update", id, phase),
  releaseConversation: (id) => ipcRenderer.invoke("conversation-release", id),
  stopConversation: () => ipcRenderer.invoke("conversation-stop"),
  onConversation: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("conversation-state", listener);
    return () => ipcRenderer.removeListener("conversation-state", listener);
  },
  onReminder: (callback) => {
    const listener = (_event, title) => callback(title);
    ipcRenderer.on("reminder", listener);
    return () => ipcRenderer.removeListener("reminder", listener);
  },
  onStop: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("stop-all", listener);
    return () => ipcRenderer.removeListener("stop-all", listener);
  },
  onOffline: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("core-offline", listener);
    return () => ipcRenderer.removeListener("core-offline", listener);
  },
});
