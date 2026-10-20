const STARTUP_ARGS = ["--autostart"];

function startupPreferences(app, { test = false, platform = process.platform } = {}) {
  const available = platform === "win32" && app.isPackaged && !test;
  const options = () => ({ path: process.execPath, args: STARTUP_ARGS });
  return {
    get() {
      return { available, enabled: available && Boolean(app.getLoginItemSettings(options()).openAtLogin) };
    },
    set(enabled) {
      if (typeof enabled !== "boolean") throw new Error("Нужен переключатель автозапуска");
      if (!available) throw new Error("Автозапуск доступен в установленной версии Windows");
      app.setLoginItemSettings({ ...options(), openAtLogin: enabled });
      return this.get();
    },
  };
}
module.exports = { startupPreferences, STARTUP_ARGS };
