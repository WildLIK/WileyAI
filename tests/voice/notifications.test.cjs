const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createNotificationDelivery,
} = require("../../desktop/notifications.cjs");
const connection = () => ({ url: "http://core.local", token: "test-token" });
const json = (value, status = 200) =>
  new Response(JSON.stringify(value), { status });

test("notifications: display current claimed data once, skip cancelled and already claimed records", async () => {
  const shown = [],
    calls = [];
  let claimed = false;
  const poll = createNotificationDelivery({
    connection,
    enabled: () => true,
    display: (item) => shown.push(item),
    fetcher: async (url, options) => {
      calls.push({
        url,
        method: options.method,
        token: options.headers.Authorization,
      });
      if (url.endsWith("/notifications"))
        return json([
          { id: "cancelled", title: "Old" },
          { id: "valid", title: "Old" },
        ]);
      if (url.endsWith("/valid/claim") && !claimed) {
        claimed = true;
        return json({ id: "valid", kind: "calendar", title: "Updated event" });
      }
      return json(null);
    },
  });
  await poll();
  await poll();
  assert.deepEqual(shown, [
    { id: "valid", kind: "calendar", title: "Updated event" },
  ]);
  assert.ok(calls.every((call) => call.token === "Bearer test-token"));
  assert.ok(
    calls
      .filter((call) => call.url.endsWith("/claim"))
      .every((call) => call.method === "POST"),
  );
});

test("notifications: concurrent polls share one worker and restore blocks a pending delivery", async () => {
  let finish,
    enabled = true,
    requests = 0;
  const response = new Promise((resolve) => {
    finish = resolve;
  });
  const shown = [];
  const poll = createNotificationDelivery({
    connection,
    enabled: () => enabled,
    display: (item) => shown.push(item),
    fetcher: async () => {
      requests++;
      return response;
    },
  });
  const first = poll();
  assert.equal(poll.active, true);
  await poll();
  assert.equal(requests, 1);
  enabled = false;
  finish(json([{ id: "before-restore" }]));
  await first;
  assert.equal(poll.active, false);
  assert.equal(requests, 1);
  assert.deepEqual(shown, []);
  await poll();
  assert.equal(requests, 1);
});

test("notifications: failed poll releases the worker and unclaimed records can retry", async () => {
  let requests = 0;
  const shown = [];
  const poll = createNotificationDelivery({
    connection,
    enabled: () => true,
    display: (item) => shown.push(item),
    fetcher: async (url) => {
      if (++requests === 1) throw new Error("Core temporarily unavailable");
      return url.endsWith("/notifications")
        ? json([{ id: "task" }])
        : json({ id: "task", kind: "task", title: "Reminder" });
    },
  });
  await poll();
  assert.deepEqual(shown, []);
  await poll();
  assert.deepEqual(shown, [{ id: "task", kind: "task", title: "Reminder" }]);
});

test("notifications: a failed claim does not prevent another valid alert", async () => {
  const shown = [];
  const poll = createNotificationDelivery({
    connection,
    enabled: () => true,
    display: (item) => shown.push(item),
    fetcher: async (url) => {
      if (url.endsWith("/notifications"))
        return json([{ id: "failed" }, { id: "ready" }]);
      return url.endsWith("/failed/claim")
        ? json({}, 503)
        : json({ id: "ready", title: "Next alert" });
    },
  });
  await poll();
  assert.deepEqual(shown, [{ id: "ready", title: "Next alert" }]);
});
