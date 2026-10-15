const { randomUUID } = require("node:crypto");
const phases = new Set([
  "preparing",
  "listening",
  "hearing",
  "transcribing",
  "thinking",
  "speaking",
]);

/** One explicitly started microphone session for all windows, with stale-lease protection. */
class ConversationLease {
  constructor(changed = () => {}) {
    this.lease = null;
    this.changed = changed;
  }
  state(sender) {
    return {
      active: Boolean(this.lease),
      owner: this.lease?.sender === sender,
      phase: this.lease?.phase || "idle",
    };
  }
  acquire(sender) {
    if (this.lease)
      throw new Error("Разговор уже включён. Сначала завершите текущий сеанс.");
    const id = randomUUID();
    this.lease = { id, sender, phase: "preparing" };
    this.changed();
    return id;
  }
  update(sender, id, phase) {
    if (
      this.lease?.sender !== sender ||
      this.lease.id !== id ||
      !phases.has(phase)
    )
      return;
    this.lease.phase = phase;
    this.changed();
  }
  release(sender, id) {
    if (this.lease?.sender !== sender || this.lease.id !== id) return;
    this.lease = null;
    this.changed();
  }
  releaseSender(sender) {
    if (this.lease?.sender === sender) this.release(sender, this.lease.id);
  }
  stop() {
    const sender = this.lease?.sender;
    this.lease = null;
    this.changed();
    return sender;
  }
}
module.exports = { ConversationLease };
