/**
 * The text of the answer being streamed. Tokens are collected and published
 * once per animation frame to the subscribed view, so the rest of the window
 * does not re-render for every token. A timer covers windows where animation
 * frames are throttled.
 */
export function createAnswerStore() {
  let value = "";
  let pending = "";
  let frame = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((listener) => listener());
  const cancel = () => {
    cancelAnimationFrame(frame);
    clearTimeout(timer);
    frame = 0;
    timer = undefined;
  };
  const flush = () => {
    cancel();
    if (!pending) return;
    value += pending;
    pending = "";
    emit();
  };
  return {
    get: () => value,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    append(text: string) {
      pending += text;
      if (frame) return;
      frame = requestAnimationFrame(flush);
      timer = setTimeout(flush, 100);
    },
    clear() {
      cancel();
      pending = "";
      if (!value) return;
      value = "";
      emit();
    },
  };
}
export type AnswerStore = ReturnType<typeof createAnswerStore>;
