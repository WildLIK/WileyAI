import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import testTemp from "./test-temp.cjs";

const python = resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const args = process.argv.slice(2);
const testing = args[0] === "-m" && args[1] === "pytest";
if (testing) await testTemp.cleanupAbandonedRuns();
const run = testing ? await testTemp.createTestRun() : undefined;
let status = 1;
try {
  if (
    run &&
    !args.some((arg) => arg === "--basetemp" || arg.startsWith("--basetemp="))
  )
    args.push("--basetemp", resolve(run.root, "pytest"));
  const result = spawnSync(python, args, {
    stdio: "inherit",
    env: run
      ? { ...process.env, TEMP: run.root, TMP: run.root, TMPDIR: run.root }
      : process.env,
  });
  if (result.error) console.error(result.error.message);
  status = result.status ?? 1;
} finally {
  if (run) await testTemp.cleanupTestRun(run);
}
process.exitCode = status;
