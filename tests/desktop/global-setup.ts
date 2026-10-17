import testTemp from "../../scripts/test-temp.cjs";

export default async function globalSetup() {
  await testTemp.cleanupAbandonedRuns();
  const run = await testTemp.createTestRun();
  const previous = {
    TEMP: process.env.TEMP,
    TMP: process.env.TMP,
    TMPDIR: process.env.TMPDIR,
  };
  process.env.TEMP = run.root;
  process.env.TMP = run.root;
  process.env.TMPDIR = run.root;
  return async () => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await testTemp.cleanupTestRun(run);
  };
}
