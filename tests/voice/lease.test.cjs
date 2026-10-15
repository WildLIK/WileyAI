const test = require("node:test");
const assert = require("node:assert/strict");
const { ConversationLease } = require("../../desktop/conversation.cjs");

test("only one window owns a conversation; another window cannot mutate its lease", () => {
  const leases = new ConversationLease();
  const id = leases.acquire(1);
  assert.throws(() => leases.acquire(2));
  leases.update(2, id, "speaking");
  assert.equal(leases.state(1).phase, "preparing");
  leases.release(2, id);
  assert.equal(leases.state(2).active, true);
  assert.equal(leases.state(2).owner, false);
  leases.releaseSender(1);
  assert.equal(leases.state(2).active, false);
});
test("late cleanup from an old session cannot release a newer session in the same window", () => {
  const leases = new ConversationLease();
  const old = leases.acquire(1);
  assert.equal(leases.stop(), 1);
  const current = leases.acquire(1);
  leases.release(1, old);
  leases.update(1, old, "speaking");
  assert.equal(leases.state(1).active, true);
  assert.equal(leases.state(1).phase, "preparing");
  leases.release(1, current);
  assert.equal(leases.state(1).phase, "idle");
});
