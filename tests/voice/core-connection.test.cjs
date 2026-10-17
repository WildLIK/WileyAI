const test = require("node:test");
const assert = require("node:assert/strict");
const {
  CoreConnection,
  portFromOutput,
} = require("../../desktop/core-connection.cjs");

test("startup: every early window waits for the same ready connection", async () => {
  const core = new CoreConnection();
  let completed = 0;
  const first = core.wait().then((info) => {
    completed++;
    return info;
  });
  const second = core.wait().then((info) => {
    completed++;
    return info;
  });
  await Promise.resolve();
  assert.equal(completed, 0);
  const info = { url: "http://127.0.0.1:54321", token: "a".repeat(64) };
  assert.equal(core.ready(info), true);
  assert.deepEqual(await first, info);
  assert.deepEqual(await second, info);
  assert.equal(completed, 2);
  assert.equal(core.ready({ url: "wrong", token: "wrong" }), false);
  assert.deepEqual(await core.wait(), info);
});

test("startup: a failure reaches pending windows and later callers; late health cannot revive it", async () => {
  const core = new CoreConnection();
  const pending = core.wait();
  const error = new Error("Ядро не запустилось за 30 секунд");
  core.fail(error);
  await assert.rejects(pending, error);
  await assert.rejects(core.wait(), error);
  assert.equal(
    core.ready({ url: "http://127.0.0.1:50000", token: "a".repeat(64) }),
    false,
  );
});

test("startup: a crash after successful startup rejects new connections", async () => {
  const core = new CoreConnection();
  core.ready({ url: "http://127.0.0.1:50000", token: "a".repeat(64) });
  await core.wait();
  core.fail(new Error("Ядро завершилось с кодом 1"));
  await assert.rejects(core.wait(), /кодом 1/);
});

test("startup: failure before any window has no unhandled rejection", async () => {
  const core = new CoreConnection();
  core.fail(new Error("Python недоступен"));
  await new Promise((resolve) => setImmediate(resolve));
  await assert.rejects(core.wait(), /Python/);
});

test("startup: stdout port announcement must be a complete valid line", () => {
  assert.equal(portFromOutput("WILEYAI_PORT=51"), undefined);
  assert.equal(portFromOutput("WILEYAI_PORT=51234\r"), undefined);
  assert.equal(portFromOutput("WILEYAI_PORT=51234\r\n"), 51234);
  assert.equal(
    portFromOutput("Import log\nWILEYAI_PORT=51234\nMore log"),
    51234,
  );
  for (const value of [
    "WILEYAI_PORT=0\n",
    "WILEYAI_PORT=65536\n",
    "WILEYAI_PORT=123456\n",
    "prefix WILEYAI_PORT=1234\n",
  ])
    assert.equal(portFromOutput(value), undefined);
});
