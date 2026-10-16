function createNotificationDelivery({
  connection,
  enabled,
  display,
  fetcher = fetch,
}) {
  let polling = false;
  async function poll() {
    const current = connection();
    if (!current || polling || !enabled()) return;
    polling = true;
    try {
      const headers = { Authorization: "Bearer " + current.token };
      const response = await fetcher(current.url + "/notifications", {
        headers,
        signal: AbortSignal.timeout(3000),
      });
      if (!response.ok) return;
      for (const candidate of await response.json()) {
        if (!enabled()) return;
        const claimed = await fetcher(
          current.url +
            "/notifications/" +
            encodeURIComponent(candidate.id) +
            "/claim",
          {
            method: "POST",
            headers,
            signal: AbortSignal.timeout(3000),
          },
        );
        if (!claimed.ok) continue;
        const item = await claimed.json();
        // Schedule and delivery state may have changed since the initial list.
        if (item && enabled()) await display(item);
      }
    } catch {
      // Unclaimed records remain in SQLite for the next poll. Claimed records
      // are not replayed after a crash or an uncertain HTTP response.
    } finally {
      polling = false;
    }
  }
  Object.defineProperty(poll, "active", { get: () => polling });
  return poll;
}
module.exports = { createNotificationDelivery };
