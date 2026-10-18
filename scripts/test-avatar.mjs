import { spawnSync } from "node:child_process";
import testTemp from "./test-temp.cjs";

await testTemp.cleanupAbandonedRuns();
const run = await testTemp.createTestRun();
try {
  const result = spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--test", "tests/avatar/*.test.ts"],
    {
      stdio: "inherit",
      env: { ...process.env, TEMP: run.root, TMP: run.root, TMPDIR: run.root },
      windowsHide: true,
    },
  );
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} finally {
  await testTemp.cleanupTestRun(run);
}
