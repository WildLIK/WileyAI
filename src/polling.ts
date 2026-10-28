/**
 * Poll with a setTimeout chain: one request in flight at a time, the next one
 * scheduled only after the previous finished, and no polling in a hidden
 * window. Returning to the window polls at once. The task must handle its own
 * errors; the signal is aborted when polling stops or the window is hidden.
 */
export function poll(
  task: (signal: AbortSignal) => Promise<unknown>,
  interval: number,
  { immediate = true }: { immediate?: boolean } = {},
) {
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  const schedule = () => {
    clearTimeout(timer);
    if (!disposed && !document.hidden) timer = setTimeout(tick, interval);
  };
  async function tick() {
    clearTimeout(timer);
    if (disposed || document.hidden || controller) return;
    const current = new AbortController();
    controller = current;
    try {
      await task(current.signal);
    } catch {
      /* The task reports its own errors. */
    } finally {
      if (controller === current) {
        controller = undefined;
        schedule();
      }
    }
  }
  const visibility = () => {
    if (!document.hidden) return void tick();
    clearTimeout(timer);
    controller?.abort();
    controller = undefined;
  };
  document.addEventListener("visibilitychange", visibility);
  if (immediate) void tick();
  else schedule();
  return () => {
    disposed = true;
    clearTimeout(timer);
    controller?.abort();
    document.removeEventListener("visibilitychange", visibility);
  };
}
