const fs = require("node:fs/promises");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

const MAX_BYTES = 64 * 1024 * 1024;

function installBackups({
  ipcMain,
  dialog,
  BrowserWindow,
  trusted,
  getConnection,
  isBusy,
  restored,
}) {
  const state = { restoring: false };
  async function api(route, options = {}) {
    const connection = getConnection();
    if (!connection) throw new Error("Ядро ещё не запущено");
    const response = await fetch(connection.url + route, {
      ...options,
      headers: {
        Authorization: "Bearer " + connection.token,
        ...options.headers,
      },
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(
        typeof error.detail === "string"
          ? error.detail
          : "Не удалось обработать копию",
      );
    }
    return response;
  }
  ipcMain.handle("backup-export", async (event) => {
    trusted(event);
    const result = await dialog.showSaveDialog(
      BrowserWindow.fromWebContents(event.sender),
      {
        title: "Сохранить резервную копию WileyAI",
        defaultPath:
          "WileyAI-" + new Date().toISOString().slice(0, 10) + ".wileyai.json",
        filters: [{ name: "Копия WileyAI", extensions: ["json"] }],
      },
    );
    if (result.canceled || !result.filePath) return null;
    const destination = result.filePath.toLowerCase().endsWith(".json")
      ? result.filePath
      : result.filePath + ".wileyai.json";
    if (destination !== result.filePath) {
      const exists = await fs.stat(destination).then(
        () => true,
        (error) => {
          if (error.code === "ENOENT") return false;
          throw error;
        },
      );
      if (exists)
        throw new Error(
          "Файл с расширением .wileyai.json уже существует. Выберите другое имя",
        );
    }
    const bytes = Buffer.from(
      await (await api("/backups/export")).arrayBuffer(),
    );
    if (bytes.length > MAX_BYTES) throw new Error("Копия превышает 64 МБ");
    const temporary = destination + "." + randomUUID() + ".tmp";
    let created = false;
    try {
      const file = await fs.open(temporary, "wx", 0o600);
      created = true;
      try {
        await file.writeFile(bytes);
        await file.sync();
      } finally {
        await file.close();
      }
      await fs.rename(temporary, destination);
    } finally {
      if (created) await fs.rm(temporary, { force: true }).catch(() => {});
    }
    return { path: destination, bytes: bytes.length };
  });
  ipcMain.handle("backup-preview", async (event) => {
    trusted(event);
    const result = await dialog.showOpenDialog(
      BrowserWindow.fromWebContents(event.sender),
      {
        title: "Выбрать копию WileyAI",
        properties: ["openFile"],
        filters: [{ name: "Копия WileyAI", extensions: ["json"] }],
      },
    );
    if (result.canceled || !result.filePaths[0]) return null;
    const filename = result.filePaths[0];
    const stat = await fs.stat(filename);
    if (!stat.isFile() || stat.size > MAX_BYTES)
      throw new Error("Выберите файл копии до 64 МБ");
    const bytes = await fs.readFile(filename);
    if (bytes.length > MAX_BYTES) throw new Error("Копия превышает 64 МБ");
    const form = new FormData();
    form.append(
      "file",
      new Blob([bytes], { type: "application/json" }),
      path.basename(filename),
    );
    const preview = await (
      await api("/backups/preview", { method: "POST", body: form })
    ).json();
    return { ...preview, filename: path.basename(filename) };
  });
  ipcMain.handle("backup-restore", async (event, options) => {
    trusted(event);
    if (
      !options ||
      !/^[a-f0-9]{32}$/.test(options.ticket) ||
      typeof options.connections !== "boolean" ||
      typeof options.aliases !== "boolean"
    )
      throw new Error("Сначала выберите и проверьте копию");
    if (state.restoring || isBusy())
      throw new Error(
        "Завершите разговор и дождитесь окончания текущей операции",
      );
    state.restoring = true;
    try {
      const result = await (
        await api("/backups/restore", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(options),
        })
      ).json();
      restored();
      return result;
    } finally {
      state.restoring = false;
    }
  });
  return state;
}

module.exports = { installBackups };
