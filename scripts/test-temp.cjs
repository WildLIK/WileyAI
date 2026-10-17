const fs = require("node:fs/promises");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

const TEST_ROOT = path.resolve(__dirname, "../local/test-runs");
const OWNER = "wileyai.automated-tests";
const same = (a, b) =>
  process.platform === "win32" ? a.toLowerCase() === b.toLowerCase() : a === b;
function inside(value, parent) {
  const relative = path.relative(parent, value);
  return (
    relative &&
    relative !== ".." &&
    !relative.startsWith(".." + path.sep) &&
    !path.isAbsolute(relative)
  );
}

async function checkedParent(parent) {
  const resolved = path.resolve(parent);
  if (!same(resolved, TEST_ROOT) && !inside(resolved, TEST_ROOT))
    throw new Error("Test directory must stay inside local/test-runs");
  if (
    !same(await fs.realpath(TEST_ROOT), TEST_ROOT) ||
    !same(await fs.realpath(resolved), resolved)
  )
    throw new Error("Test directory cannot be redirected by a symlink");
  return resolved;
}

async function createTestRun(parent = TEST_ROOT) {
  await fs.mkdir(parent, { recursive: true });
  parent = await checkedParent(parent);
  const root = await fs.mkdtemp(path.join(parent, "run-"));
  const run = {
    root,
    parent,
    owner: OWNER,
    id: randomUUID(),
    pid: process.pid,
  };
  await fs.writeFile(
    path.join(root, ".wiley-test-run.json"),
    JSON.stringify(run),
  );
  return run;
}

async function cleanupTestRun(run) {
  const parent = await checkedParent(run.parent);
  const root = path.resolve(run.root);
  if (
    !same(path.dirname(root), parent) ||
    !/^run-[A-Za-z0-9]{6}$/.test(path.basename(root)) ||
    !same(await fs.realpath(root), root) ||
    (await fs.lstat(root)).isSymbolicLink()
  )
    throw new Error("Invalid test cleanup target");
  const marker = JSON.parse(
    await fs.readFile(path.join(root, ".wiley-test-run.json"), "utf8"),
  );
  if (
    marker.owner !== OWNER ||
    marker.id !== run.id ||
    !same(marker.root, root) ||
    !same(marker.parent, parent)
  )
    throw new Error("Test ownership marker does not match");
  // fs.rm unlinks junctions/symlinks instead of traversing their targets. Native
  // model tests deliberately link to real weights, which must remain untouched.
  await fs.rm(root, { recursive: true, maxRetries: 10, retryDelay: 200 });
}

async function cleanupAbandonedRuns() {
  await fs.mkdir(TEST_ROOT, { recursive: true });
  const parent = await checkedParent(TEST_ROOT);
  for (const entry of await fs.readdir(parent, { withFileTypes: true })) {
    if (!entry.isDirectory() || !/^run-[A-Za-z0-9]{6}$/.test(entry.name))
      continue;
    const root = path.join(parent, entry.name);
    let run;
    try {
      run = JSON.parse(
        await fs.readFile(path.join(root, ".wiley-test-run.json"), "utf8"),
      );
    } catch {
      continue;
    }
    if (run.owner !== OWNER || !Number.isSafeInteger(run.pid) || run.pid <= 0)
      continue;
    try {
      process.kill(run.pid, 0);
    } catch (error) {
      if (error.code === "ESRCH") await cleanupTestRun(run);
    }
  }
}

module.exports = {
  TEST_ROOT,
  createTestRun,
  cleanupTestRun,
  cleanupAbandonedRuns,
};
