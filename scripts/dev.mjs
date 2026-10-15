import { createServer } from "vite";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const server = await createServer();
await server.listen();
server.printUrls();
const child = spawn(require("electron"), ["."], {
  stdio: "inherit",
  env: { ...process.env, WILEYAI_DEV: "1" },
});
child.on("exit", async (code) => {
  await server.close();
  process.exit(code ?? 0);
});
process.on("SIGINT", () => child.kill());
