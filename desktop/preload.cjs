const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wiley", {
  connection: () => ipcRenderer.invoke("connection"),
  showWindow: (view) => ipcRenderer.invoke("show-window", view),
  pickFile: (kind) => ipcRenderer.invoke("pick-file", kind),
  avatarBytes: () => ipcRenderer.invoke("avatar-bytes"),
  clickThrough: (enabled) => ipcRenderer.invoke("avatar-clickthrough", enabled),
  quit: () => ipcRenderer.invoke("quit"),
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
