const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wiley", {
  connection: () => ipcRenderer.invoke("connection"),
  showWindow: (view) => ipcRenderer.invoke("show-window", view),
  pickFile: (kind) => ipcRenderer.invoke("pick-file", kind),
  avatarBytes: () => ipcRenderer.invoke("avatar-bytes"),
  clickThrough: (enabled) => ipcRenderer.invoke("avatar-clickthrough", enabled),
  quit: () => ipcRenderer.invoke("quit"),
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
