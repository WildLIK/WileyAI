const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const {
  TEST_ROOT,
  createTestRun,
  cleanupTestRun,
} = require("../../scripts/test-temp.cjs");

test("test cleanup removes only a marked run; model junction targets survive", async () => {
  const container = await createTestRun();
  try {
    const parent = path.join(container.root, "nested");
    const run = await createTestRun(parent);
    const keep = path.join(container.root, "weights");
    await fs.mkdir(keep);
    await fs.writeFile(path.join(keep, "model.bin"), "preserve-model");
    await fs.symlink(
      keep,
      path.join(run.root, "real-model"),
      process.platform === "win32" ? "junction" : "dir",
    );
    await fs.writeFile(path.join(run.root, "temporary"), "delete-me");
    await cleanupTestRun(run);
    await assert.rejects(fs.access(run.root));
    assert.equal(
      await fs.readFile(path.join(keep, "model.bin"), "utf8"),
      "preserve-model",
    );
    assert.ok(container.root.startsWith(TEST_ROOT + path.sep));
  } finally {
    await cleanupTestRun(container);
  }
});

test("test cleanup refuses a changed marker, an outside path, and the whole test root", async () => {
  const run = await createTestRun();
  try {
    await assert.rejects(cleanupTestRun({ ...run, id: "different" }), /marker/);
    await assert.rejects(
      cleanupTestRun({ ...run, root: path.dirname(TEST_ROOT) }),
      /target/,
    );
    await assert.rejects(cleanupTestRun({ ...run, root: TEST_ROOT }), /target/);
    assert.equal((await fs.stat(run.root)).isDirectory(), true);
  } finally {
    await cleanupTestRun(run);
  }
});
