// One readiness promise for every window, including a second-instance window
// opened while Python is still importing. Never hand an undefined URL to IPC.
class CoreConnection {
  constructor() {
    this.state = "starting";
    this.promise = new Promise((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
    // Startup may fail before any renderer has asked for the connection.
    void this.promise.catch(() => {});
  }

  ready(info) {
    if (this.state !== "starting") return false;
    this.state = "ready";
    this.resolve({ url: info.url, token: info.token });
    return true;
  }

  fail(error) {
    if (this.state === "failed") return;
    this.state = "failed";
    this.error =
      error instanceof Error ? error : new Error("Локальное ядро недоступно");
    this.reject(this.error);
  }

  wait() {
    return this.state === "failed" ? Promise.reject(this.error) : this.promise;
  }
}

function portFromOutput(output) {
  // stdout arrives in arbitrary chunks; wait for the ENTIRE announcement line.
  const match = output.match(/(?:^|\n)WILEYAI_PORT=(\d{1,5})\r?\n/);
  const port = match ? Number(match[1]) : 0;
  return port > 0 && port <= 65535 ? port : undefined;
}

module.exports = { CoreConnection, portFromOutput };
